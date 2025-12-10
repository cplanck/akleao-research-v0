"""Text chunking module - splits documents into smaller pieces for embedding."""

from dataclasses import dataclass
from .ingest import Document


@dataclass
class Chunk:
    """Represents a chunk of text from a document."""
    content: str
    source: str
    doc_id: str
    chunk_index: int
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        self.id = f"{self.doc_id}_{self.chunk_index}"


class Chunker:
    """Splits documents into chunks with configurable overlap."""

    # Approximate chars per token (conservative estimate)
    CHARS_PER_TOKEN = 4

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        # Convert token counts to character counts
        self.chunk_size = chunk_size * self.CHARS_PER_TOKEN
        self.chunk_overlap = chunk_overlap * self.CHARS_PER_TOKEN

    def chunk_document(self, document: Document) -> list[Chunk]:
        """Split a document into chunks."""
        # If document has segments with page info, use segment-aware chunking
        if document.segments:
            return self._chunk_with_segments(document)

        # Otherwise, fall back to simple text chunking
        return self._chunk_text(document)

    def _chunk_with_segments(self, document: Document) -> list[Chunk]:
        """Chunk document using segments with page number tracking."""
        chunks = []
        current_chunk_text = ""
        current_pages = set()
        current_sections = set()

        for segment in document.segments:
            segment_text = segment.text.strip()
            if not segment_text:
                continue

            # Would adding this segment exceed chunk size?
            combined = current_chunk_text + "\n\n" + segment_text if current_chunk_text else segment_text

            if len(combined) > self.chunk_size and current_chunk_text:
                # Save current chunk
                chunks.append(self._create_chunk(
                    document=document,
                    text=current_chunk_text,
                    chunk_index=len(chunks),
                    pages=current_pages,
                    sections=current_sections
                ))
                # Start new chunk with current segment
                current_chunk_text = segment_text
                current_pages = {segment.page_number} if segment.page_number else set()
                current_sections = {segment.section} if segment.section else set()
            else:
                # Add to current chunk
                current_chunk_text = combined
                if segment.page_number:
                    current_pages.add(segment.page_number)
                if segment.section:
                    current_sections.add(segment.section)

        # Don't forget the last chunk
        if current_chunk_text.strip():
            chunks.append(self._create_chunk(
                document=document,
                text=current_chunk_text,
                chunk_index=len(chunks),
                pages=current_pages,
                sections=current_sections
            ))

        return chunks

    def _create_chunk(
        self,
        document: Document,
        text: str,
        chunk_index: int,
        pages: set,
        sections: set
    ) -> Chunk:
        """Create a chunk with page and section metadata."""
        # Sort pages for consistent display
        page_list = sorted([p for p in pages if p is not None])
        section_list = [s for s in sections if s is not None]

        metadata = {
            **document.metadata,
            "doc_type": document.doc_type,
            "char_count": len(text),
        }

        # Add page info if available
        if page_list:
            # Store as comma-separated string for Pinecone compatibility
            metadata["page_numbers"] = ",".join(str(p) for p in page_list)
            # Create human-readable page reference
            if len(page_list) == 1:
                metadata["page_ref"] = f"p. {page_list[0]}"
            else:
                metadata["page_ref"] = f"pp. {page_list[0]}-{page_list[-1]}"

        # Add section info if available (as string for Pinecone)
        if section_list:
            metadata["sections"] = "; ".join(section_list)

        return Chunk(
            content=text,
            source=document.source,
            doc_id=document.id,
            chunk_index=chunk_index,
            metadata=metadata
        )

    def _chunk_text(self, document: Document) -> list[Chunk]:
        """Simple text-based chunking (fallback for non-PDF documents)."""
        text = document.content
        chunks = []
        start = 0

        while start < len(text):
            end = start + self.chunk_size

            # Try to break at a sentence or paragraph boundary
            chunk_text = text[start:end]

            # If we're not at the end, try to find a good break point
            if end < len(text):
                # Look for paragraph break first
                last_para = chunk_text.rfind('\n\n')
                if last_para > self.chunk_size // 2:
                    chunk_text = chunk_text[:last_para]
                    end = start + last_para
                else:
                    # Look for sentence break
                    for sep in ['. ', '.\n', '? ', '!\n']:
                        last_sep = chunk_text.rfind(sep)
                        if last_sep > self.chunk_size // 2:
                            chunk_text = chunk_text[:last_sep + 1]
                            end = start + last_sep + 1
                            break

            chunk_text = chunk_text.strip()
            if chunk_text:
                chunks.append(Chunk(
                    content=chunk_text,
                    source=document.source,
                    doc_id=document.id,
                    chunk_index=len(chunks),
                    metadata={
                        **document.metadata,
                        "doc_type": document.doc_type,
                        "char_count": len(chunk_text),
                    }
                ))

            # Move forward by (chunk_size - overlap)
            start = end - self.chunk_overlap

            # Avoid infinite loop on small remaining text
            if start >= len(text) - self.chunk_overlap:
                break

        return chunks

    def chunk_documents(self, documents: list[Document]) -> list[Chunk]:
        """Split multiple documents into chunks."""
        all_chunks = []
        for doc in documents:
            all_chunks.extend(self.chunk_document(doc))
        return all_chunks

    def count_tokens(self, text: str) -> int:
        """Estimate token count from character count."""
        return len(text) // self.CHARS_PER_TOKEN
