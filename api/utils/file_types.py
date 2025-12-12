"""File type detection and categorization utilities."""

from enum import Enum
from pathlib import Path

from api.database import ResourceType


class FileCategory(str, Enum):
    """High-level file category for routing to processing pipeline."""
    RAG = "rag"        # Semantic search via Pinecone (PDF, DOCX, MD, TXT)
    DATA = "data"      # Structured data analysis (CSV, Excel, JSON)
    IMAGE = "image"    # Vision analysis (PNG, JPG, etc.)
    UNKNOWN = "unknown"


# Extension mappings
RAG_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".markdown", ".html"}
DATA_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".parquet", ".tsv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff"}

# MIME type mappings (for content-type detection)
RAG_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/plain",
    "text/html",
}
DATA_MIME_TYPES = {
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/json",
}
IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",
}


def detect_file_category(filename: str) -> FileCategory:
    """Determine the processing category based on file extension.
    
    Args:
        filename: The name of the file (with extension)
        
    Returns:
        FileCategory indicating how the file should be processed
    """
    ext = Path(filename).suffix.lower()
    
    if ext in RAG_EXTENSIONS:
        return FileCategory.RAG
    elif ext in DATA_EXTENSIONS:
        return FileCategory.DATA
    elif ext in IMAGE_EXTENSIONS:
        return FileCategory.IMAGE
    
    return FileCategory.UNKNOWN


def get_resource_type(filename: str, category: FileCategory = None) -> ResourceType:
    """Map file to ResourceType enum.
    
    Args:
        filename: The name of the file
        category: Optional pre-computed category
        
    Returns:
        ResourceType enum value
    """
    if category is None:
        category = detect_file_category(filename)
    
    if category == FileCategory.RAG:
        return ResourceType.DOCUMENT
    elif category == FileCategory.DATA:
        return ResourceType.DATA_FILE
    elif category == FileCategory.IMAGE:
        return ResourceType.IMAGE
    
    # Fallback to document for unknown types
    return ResourceType.DOCUMENT


def get_allowed_extensions() -> set[str]:
    """Get all allowed file extensions."""
    return RAG_EXTENSIONS | DATA_EXTENSIONS | IMAGE_EXTENSIONS


def is_allowed_extension(filename: str) -> bool:
    """Check if a file has an allowed extension."""
    ext = Path(filename).suffix.lower()
    return ext in get_allowed_extensions()


def get_category_extensions(category: FileCategory) -> set[str]:
    """Get extensions for a specific category."""
    if category == FileCategory.RAG:
        return RAG_EXTENSIONS
    elif category == FileCategory.DATA:
        return DATA_EXTENSIONS
    elif category == FileCategory.IMAGE:
        return IMAGE_EXTENSIONS
    return set()


def format_allowed_extensions() -> str:
    """Format allowed extensions for display in UI."""
    rag = ", ".join(sorted(ext.upper().lstrip(".") for ext in RAG_EXTENSIONS))
    data = ", ".join(sorted(ext.upper().lstrip(".") for ext in DATA_EXTENSIONS))
    image = ", ".join(sorted(ext.upper().lstrip(".") for ext in IMAGE_EXTENSIONS))
    
    return f"Documents: {rag} | Data: {data} | Images: {image}"
