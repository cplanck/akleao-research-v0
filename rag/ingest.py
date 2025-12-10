"""Document ingestion module - handles loading various document types."""

from pathlib import Path
from dataclasses import dataclass
from typing import Iterator
import hashlib
import tempfile
import requests
from urllib.parse import urlparse


@dataclass
class TextSegment:
    """A segment of text with page information."""
    text: str
    page_number: int | None = None
    section: str | None = None


@dataclass
class Document:
    """Represents a loaded document."""
    content: str
    source: str
    doc_type: str
    metadata: dict = None
    # For page-aware documents, this contains segments with page numbers
    segments: list[TextSegment] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.segments is None:
            self.segments = []
        # Generate a unique ID based on content hash
        self.id = hashlib.md5(self.content.encode()).hexdigest()[:12]


class DocumentLoader:
    """Loads documents from various sources."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".markdown"}

    def __init__(self, fast_mode: bool = False):
        """Initialize document loader.

        Args:
            fast_mode: If True, skip table structure recognition for faster PDF processing.
                       Good for text-heavy PDFs without complex tables.
        """
        self.fast_mode = fast_mode

    def load(self, path: str | Path) -> list[Document]:
        """Load document(s) from a file or directory path."""
        path = Path(path)

        if path.is_dir():
            return list(self._load_directory(path))
        elif path.is_file():
            return [self._load_file(path)]
        else:
            raise FileNotFoundError(f"Path not found: {path}")

    def _load_directory(self, dir_path: Path) -> Iterator[Document]:
        """Recursively load all supported documents from a directory."""
        for file_path in dir_path.rglob("*"):
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    yield self._load_file(file_path)
                except Exception as e:
                    print(f"Warning: Failed to load {file_path}: {e}")

    def _load_file(self, file_path: Path) -> Document:
        """Load a single document file."""
        suffix = file_path.suffix.lower()
        segments = []

        if suffix == ".pdf":
            content, segments = self._load_pdf(file_path)
            doc_type = "pdf"
        elif suffix == ".docx":
            content = self._load_docx(file_path)
            doc_type = "docx"
        elif suffix in {".md", ".markdown"}:
            content = self._load_text(file_path)
            doc_type = "markdown"
        elif suffix == ".txt":
            content = self._load_text(file_path)
            doc_type = "text"
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        return Document(
            content=content,
            source=str(file_path),
            doc_type=doc_type,
            metadata={"filename": file_path.name},
            segments=segments
        )

    def _load_pdf(self, file_path: Path) -> tuple[str, list[TextSegment]]:
        """Extract text from PDF using Docling for better table/image handling.

        Returns:
            tuple of (content, segments_with_page_numbers)
        """
        try:
            return self._load_pdf_with_docling(file_path)
        except Exception as e:
            print(f"Docling failed, falling back to pypdf: {e}")
            # Basic fallback doesn't have page-level segments
            content = self._load_pdf_basic(file_path)
            return content, []

    def _load_pdf_basic(self, file_path: Path) -> str:
        """Basic PDF extraction using pypdf (fallback)."""
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        text_parts = []

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                text_parts.append(text)

        return "\n\n".join(text_parts)

    def _load_pdf_with_docling(self, file_path: Path) -> tuple[str, list[TextSegment]]:
        """Extract text from PDF using Docling - handles tables and images.

        Returns:
            tuple of (full_markdown_content, list_of_segments_with_page_numbers)
        """
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        # Configure Docling - skip table structure in fast mode for ~3-5x speedup
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # Disable OCR for faster processing
        pipeline_options.do_table_structure = not self.fast_mode  # Skip in fast mode

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        result = converter.convert(str(file_path))
        doc = result.document

        # Extract segments with page numbers
        segments = []
        current_section = None

        for item, level in doc.iterate_items():
            # Track section headers
            if type(item).__name__ == 'SectionHeaderItem':
                current_section = getattr(item, 'text', None)

            # Get text content
            text = getattr(item, 'text', None)
            if not text:
                # For tables, try to get markdown representation
                if type(item).__name__ == 'TableItem':
                    try:
                        text = item.export_to_markdown()
                    except:
                        continue
                else:
                    continue

            # Get page number from provenance
            page_no = None
            if hasattr(item, 'prov') and item.prov:
                prov = item.prov[0]  # Take first provenance item
                if hasattr(prov, 'page_no'):
                    page_no = prov.page_no

            segments.append(TextSegment(
                text=text.strip(),
                page_number=page_no,
                section=current_section
            ))

        # Export as markdown for full content (preserves table structure)
        full_content = doc.export_to_markdown()

        return full_content, segments

    def _load_docx(self, file_path: Path) -> str:
        """Extract text from Word document."""
        from docx import Document as DocxDocument

        doc = DocxDocument(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]

        return "\n\n".join(paragraphs)

    def _load_text(self, file_path: Path) -> str:
        """Load plain text or markdown file."""
        return file_path.read_text(encoding="utf-8")

    def load_url(self, url: str) -> Document:
        """Load document from a URL. Supports PDFs and webpages."""
        parsed = urlparse(url)
        if not parsed.scheme in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

        # Download the content with browser-like headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        response = requests.get(url, timeout=60, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").lower()
        path_lower = parsed.path.lower()

        # Check actual content magic bytes for more reliable detection
        content_start = response.content[:8] if len(response.content) >= 8 else response.content
        is_pdf_content = content_start.startswith(b'%PDF')
        is_html_content = content_start.lstrip().lower().startswith((b'<!doc', b'<html', b'<head'))

        # Determine file type - prioritize actual content over URL/headers
        if is_pdf_content:
            return self._load_pdf_from_bytes(response.content, url)
        elif "application/pdf" in content_type and not is_html_content:
            return self._load_pdf_from_bytes(response.content, url)
        elif path_lower.endswith(".docx") and not is_html_content:
            return self._load_docx_from_bytes(response.content, url)
        elif path_lower.endswith((".md", ".markdown")) and not is_html_content:
            return Document(
                content=response.text,
                source=url,
                doc_type="markdown",
                metadata={"url": url}
            )
        elif path_lower.endswith(".txt") and not is_html_content:
            return Document(
                content=response.text,
                source=url,
                doc_type="text",
                metadata={"url": url}
            )
        else:
            # Assume HTML webpage - extract text
            return self._load_webpage(response.text, url)

    def _load_pdf_from_bytes(self, content: bytes, source: str) -> Document:
        """Extract text from PDF bytes using Docling for better table/image handling."""
        try:
            return self._load_pdf_from_bytes_with_docling(content, source)
        except Exception as e:
            print(f"Docling failed for URL PDF, falling back to pypdf: {e}")
            return self._load_pdf_from_bytes_basic(content, source)

    def _load_pdf_from_bytes_basic(self, content: bytes, source: str) -> Document:
        """Basic PDF extraction from bytes using pypdf (fallback)."""
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(content))
        text_parts = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        return Document(
            content="\n\n".join(text_parts),
            source=source,
            doc_type="pdf",
            metadata={"url": source}
        )

    def _load_pdf_from_bytes_with_docling(self, content: bytes, source: str) -> Document:
        """Extract text from PDF bytes using Docling - handles tables and images."""
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.document import DocumentStream
        import tempfile
        import os

        # Configure Docling - skip table structure in fast mode for ~3-5x speedup
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # Disable OCR for faster processing
        pipeline_options.do_table_structure = not self.fast_mode  # Skip in fast mode

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        # Save to temp file since Docling needs a file path
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = converter.convert(tmp_path)
            # Export as markdown - this preserves table structure
            markdown_content = result.document.export_to_markdown()
        finally:
            os.unlink(tmp_path)

        return Document(
            content=markdown_content,
            source=source,
            doc_type="pdf",
            metadata={"url": source}
        )

    def _load_docx_from_bytes(self, content: bytes, source: str) -> Document:
        """Extract text from DOCX bytes."""
        from docx import Document as DocxDocument
        import io

        doc = DocxDocument(io.BytesIO(content))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]

        return Document(
            content="\n\n".join(paragraphs),
            source=source,
            doc_type="docx",
            metadata={"url": source}
        )

    def _load_webpage(self, html: str, source: str) -> Document:
        """Extract text content from HTML webpage."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()

        # Get text and clean it up
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        content = "\n".join(lines)

        # Get title if available
        title = soup.title.string if soup.title else None

        return Document(
            content=content,
            source=source,
            doc_type="webpage",
            metadata={"url": source, "title": title}
        )
