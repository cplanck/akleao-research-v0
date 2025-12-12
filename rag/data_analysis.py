"""Data analysis engine for CSV, Excel, and JSON files."""

import os
import json
import pandas as pd
from pathlib import Path
from anthropic import Anthropic


class DataAnalyzer:
    """Execute pandas queries on data files safely using LLM-generated code."""

    def __init__(self, api_key: str = None):
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def analyze(self, file_path: str, query: str, metadata: dict = None) -> str:
        """
        Execute analysis on a data file.

        Args:
            file_path: Path to the data file (CSV, Excel, JSON)
            query: Natural language description of the analysis
            metadata: Optional metadata about the file (columns, row_count, etc.)

        Returns:
            String result of the analysis
        """
        # Load data
        ext = Path(file_path).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(file_path, on_bad_lines='skip')
            elif ext == ".tsv":
                df = pd.read_csv(file_path, sep="\t", on_bad_lines='skip')
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(file_path)
            elif ext == ".json":
                df = pd.read_json(file_path)
            elif ext == ".parquet":
                df = pd.read_parquet(file_path)
            else:
                return f"Error: Unsupported file type: {ext}"
        except Exception as e:
            return f"Error loading file: {str(e)}"

        # Build context about the data
        columns_info = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            sample = df[col].dropna().head(2).tolist()
            sample_str = ", ".join([str(s)[:50] for s in sample])
            columns_info.append(f"  - {col} ({dtype}): e.g., {sample_str}")

        columns_context = "\n".join(columns_info)

        # Generate pandas code
        code = self._generate_code(query, columns_context, len(df))

        if code.startswith("Error:"):
            return code

        # Execute safely
        result = self._execute_safely(df, code)

        return result

    def _generate_code(self, query: str, columns_context: str, row_count: int) -> str:
        """Use LLM to generate pandas code from natural language query."""
        prompt = f"""Generate Python pandas code to answer this query about a DataFrame.

IMPORTANT: The DataFrame is ALREADY LOADED as 'df'. Do NOT read any files - just use df directly.

DataFrame info:
- Row count: {row_count:,}
- Columns:
{columns_context}

Query: {query}

Requirements:
1. The DataFrame is already loaded as 'df' - DO NOT use pd.read_csv or any file reading
2. Store the final result in a variable called 'result'
3. The result should be displayable (DataFrame, Series, or simple value)
4. Keep it simple - just one or two lines of pandas code
5. Do NOT use try/except blocks - just write the pandas code directly
6. Do NOT import anything - pandas (pd) and numpy (np) are already available

Return ONLY the Python code, no explanations or markdown.
Examples:
result = df.head(5)
result = df.groupby('category')['sales'].sum().sort_values(ascending=False).head(10)
result = df['price'].mean()"""

        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            code = response.content[0].text.strip()

            # Clean up code if it has markdown
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            return code
        except Exception as e:
            return f"Error: Failed to generate code: {str(e)}"

    def _execute_safely(self, df: pd.DataFrame, code: str) -> str:
        """Execute pandas code in a restricted environment."""
        import numpy as np

        # Check for dangerous patterns
        dangerous_patterns = [
            "import ", "__", "exec(", "eval(", "open(", "os.", "subprocess",
            "system(", "popen", ".write(", "delete", ".drop(", "to_csv", "to_excel",
            "to_json", "to_parquet", "shutil", "pathlib", "glob", "input(",
            "compile(", "globals(", "locals(", "getattr(", "setattr(",
            "read_csv", "read_excel", "read_json", "read_parquet",  # Block file reading
        ]
        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                return f"Error: Unsafe operation detected ({pattern}). Only read operations are allowed."

        # Safe builtins
        safe_builtins = {
            'len': len, 'sum': sum, 'min': min, 'max': max,
            'abs': abs, 'round': round, 'sorted': sorted,
            'list': list, 'dict': dict, 'str': str, 'int': int, 'float': float,
            'bool': bool, 'tuple': tuple, 'set': set,
            'True': True, 'False': False, 'None': None,
            'range': range, 'enumerate': enumerate, 'zip': zip,
            'print': print,  # Allow print for debugging
        }

        # Execution context
        exec_globals = {
            "__builtins__": safe_builtins,
            "df": df.copy(),  # Use copy to prevent modification
            "pd": pd,
            "np": np,
        }
        exec_locals = {}

        try:
            exec(code, exec_globals, exec_locals)
            result = exec_locals.get('result')

            if result is None:
                return "No result generated. Make sure your code assigns to 'result'."
            elif isinstance(result, pd.DataFrame):
                if len(result) > 50:
                    return f"Showing first 50 of {len(result)} rows:\n\n{result.head(50).to_string()}"
                return result.to_string()
            elif isinstance(result, pd.Series):
                if len(result) > 50:
                    return f"Showing first 50 of {len(result)} items:\n\n{result.head(50).to_string()}"
                return result.to_string()
            else:
                return str(result)
        except Exception as e:
            return f"Error executing analysis: {str(e)}"

    def get_schema(self, file_path: str) -> str:
        """Get schema information about a data file."""
        ext = Path(file_path).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(file_path, nrows=5)
            elif ext == ".tsv":
                df = pd.read_csv(file_path, sep="\t", nrows=5)
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(file_path, nrows=5)
            elif ext == ".json":
                df = pd.read_json(file_path)
                df = df.head(5)
            elif ext == ".parquet":
                df = pd.read_parquet(file_path)
                df = df.head(5)
            else:
                return f"Unsupported file type: {ext}"

            # Build schema description
            schema_parts = [f"File: {Path(file_path).name}"]
            schema_parts.append(f"Columns ({len(df.columns)}):")

            for col in df.columns:
                dtype = str(df[col].dtype)
                non_null = df[col].notna().sum()
                sample = df[col].dropna().head(2).tolist()
                sample_str = ", ".join([str(s)[:30] for s in sample])
                schema_parts.append(f"  - {col} ({dtype}): {sample_str}")

            return "\n".join(schema_parts)
        except Exception as e:
            return f"Error reading schema: {str(e)}"
