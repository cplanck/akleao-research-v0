"""RAG Pipeline - orchestrates the full ingestion and query flow."""

import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

from .ingest import DocumentLoader, Document
from .chunker import Chunker, Chunk
from .embeddings import Embedder
from .vectorstore import VectorStore
from .retriever import Retriever, RetrievalResult
from .llm import LLM


# Summary generation prompt
SUMMARY_SYSTEM_PROMPT = """You are a document summarizer. Generate a concise summary (2-4 sentences) that captures the key topics and content of the document.

The summary should help someone understand:
1. What type of document this is (datasheet, manual, article, etc.)
2. The main subject/topic
3. Key information it contains

Be specific about what the document covers. Use concrete terms, not vague descriptions.

Examples of good summaries:
- "Technical datasheet for the XR-500 industrial sensor. Covers electrical specifications, pinout diagrams, operating temperature ranges, and communication protocols (I2C, SPI)."
- "Employee handbook for Acme Corp. Contains policies on PTO, benefits enrollment, code of conduct, and remote work guidelines."
- "Research paper on transformer architectures in NLP. Discusses attention mechanisms, BERT, GPT models, and benchmark performance comparisons."

Respond with ONLY the summary text, no labels or prefixes."""


def generate_document_summary(
    content: str,
    filename: str = None,
    api_key: str = None,
    model: str = "claude-3-haiku-20240307",
    max_content_chars: int = 15000
) -> str:
    """Generate a concise summary of document content using an LLM.

    Args:
        content: The full document content
        filename: Optional filename to help with context
        api_key: Anthropic API key (defaults to env var)
        model: Model to use for summarization (default: Haiku for speed/cost)
        max_content_chars: Maximum characters to send to LLM (truncates if longer)

    Returns:
        A 2-4 sentence summary of the document
    """
    client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    # Truncate content if too long (sample from beginning and end)
    if len(content) > max_content_chars:
        half = max_content_chars // 2
        content = content[:half] + "\n\n[...content truncated...]\n\n" + content[-half:]

    # Build the user message
    user_message = f"Document"
    if filename:
        user_message += f" ({filename})"
    user_message += f":\n\n{content}"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=256,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[Summarizer] Error generating summary: {e}")
        return None


class RAGPipeline:
    """Main pipeline that orchestrates document ingestion and querying."""

    def __init__(
        self,
        openai_api_key: str = None,
        anthropic_api_key: str = None,
        pinecone_api_key: str = None,
        pinecone_index_name: str = "simage-rag",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        embedding_model: str = "text-embedding-3-small",
        llm_model: str = "claude-sonnet-4-20250514",
        llm_provider: str = "anthropic",
    ):
        # Load from environment if not provided
        load_dotenv()

        openai_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        pinecone_key = pinecone_api_key or os.getenv("PINECONE_API_KEY")
        index_name = pinecone_index_name or os.getenv("PINECONE_INDEX_NAME", "simage-rag")

        # Initialize components
        self.loader = DocumentLoader()
        self.chunker = Chunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = Embedder(api_key=openai_key, model=embedding_model)
        self.vectorstore = VectorStore(
            api_key=pinecone_key,
            index_name=index_name,
            dimension=self.embedder.dimensions
        )
        self.retriever = Retriever(
            embedder=self.embedder,
            vectorstore=self.vectorstore
        )

        # Use OpenAI or Anthropic for LLM
        llm_key = anthropic_key if llm_provider == "anthropic" else openai_key
        self.llm = LLM(api_key=llm_key, model=llm_model, provider=llm_provider)

        self._initialized = False

    def initialize(self) -> None:
        """Initialize the vector store (create index if needed)."""
        self.vectorstore.create_index_if_not_exists()
        self._initialized = True

    def ingest(
        self,
        path: str | Path,
        namespace: str = "",
        resource_id: str = None,
        generate_summary: bool = False
    ) -> dict:
        """Ingest documents from a file or directory.

        Args:
            path: File or directory path to ingest
            namespace: Pinecone namespace to store vectors in
            resource_id: Optional resource ID for source linking
            generate_summary: If True, generate an LLM summary of the document

        Returns:
            Dict with ingestion stats and optional summary
        """
        if not self._initialized:
            self.initialize()

        # Load documents
        print(f"Loading documents from: {path}")
        documents = self.loader.load(path)
        print(f"Loaded {len(documents)} document(s)")

        # Add resource_id to document metadata if provided
        if resource_id:
            for doc in documents:
                doc.metadata["resource_id"] = resource_id

        # Chunk documents
        print("Chunking documents...")
        chunks = self.chunker.chunk_documents(documents)
        print(f"Created {len(chunks)} chunk(s)")

        # Generate embeddings
        print("Generating embeddings...")
        chunk_embeddings = self.embedder.embed_chunks(chunks)
        embeddings = [emb for _, emb in chunk_embeddings]
        print(f"Generated {len(embeddings)} embedding(s)")

        # Store in vector database
        print("Storing in Pinecone...")
        result = self.vectorstore.upsert(chunks, embeddings, namespace=namespace)
        print(f"Upserted {result['upserted_count']} vector(s)")

        output = {
            "documents": len(documents),
            "chunks": len(chunks),
            "vectors_upserted": result["upserted_count"]
        }

        # Generate summary if requested
        if generate_summary and documents:
            print("Generating document summary...")
            # Combine all document content for summary
            combined_content = "\n\n".join(doc.content for doc in documents)
            filename = documents[0].metadata.get("filename")
            summary = generate_document_summary(combined_content, filename=filename)
            output["summary"] = summary
            print(f"Summary: {summary[:100]}..." if summary else "Summary generation failed")

        return output

    def query(
        self,
        question: str,
        top_k: int = 5,
        namespace: str = "",
        return_sources: bool = False
    ) -> str | dict:
        """Query the RAG system with a question."""
        if not self._initialized:
            self.initialize()

        # Retrieve relevant context
        results = self.retriever.retrieve(
            query=question,
            top_k=top_k,
            namespace=namespace
        )

        # Generate response
        response = self.llm.generate_with_results(question, results)

        if return_sources:
            return {
                "answer": response,
                "sources": [
                    {
                        "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                        "source": r.source,
                        "score": r.score
                    }
                    for r in results
                ]
            }

        return response

    def ingest_url(
        self,
        url: str,
        namespace: str = "",
        resource_id: str = None,
        generate_summary: bool = False
    ) -> dict:
        """Ingest content from a URL (PDF, webpage, etc.).

        Args:
            url: URL to fetch and ingest
            namespace: Pinecone namespace to store vectors in
            resource_id: Optional resource ID for source linking
            generate_summary: If True, generate an LLM summary of the document

        Returns:
            Dict with ingestion stats and optional summary
        """
        if not self._initialized:
            self.initialize()

        # Load document from URL
        print(f"Loading content from URL: {url}")
        document = self.loader.load_url(url)
        print(f"Loaded document: {document.doc_type}")

        # Add resource_id to document metadata if provided
        if resource_id:
            document.metadata["resource_id"] = resource_id

        # Chunk document
        print("Chunking document...")
        chunks = self.chunker.chunk_documents([document])
        print(f"Created {len(chunks)} chunk(s)")

        # Generate embeddings
        print("Generating embeddings...")
        chunk_embeddings = self.embedder.embed_chunks(chunks)
        embeddings = [emb for _, emb in chunk_embeddings]
        print(f"Generated {len(embeddings)} embedding(s)")

        # Store in vector database
        print("Storing in Pinecone...")
        result = self.vectorstore.upsert(chunks, embeddings, namespace=namespace)
        print(f"Upserted {result['upserted_count']} vector(s)")

        output = {
            "url": url,
            "doc_type": document.doc_type,
            "chunks": len(chunks),
            "vectors_upserted": result["upserted_count"]
        }

        # Generate summary if requested
        if generate_summary:
            print("Generating document summary...")
            # Use URL or title as filename hint
            filename = document.metadata.get("title") or url
            summary = generate_document_summary(document.content, filename=filename)
            output["summary"] = summary
            print(f"Summary: {summary[:100]}..." if summary else "Summary generation failed")

        return output

    def ingest_documents(
        self,
        documents: list[Document],
        namespace: str = "",
        resource_id: str = None,
        generate_summary: bool = False
    ) -> dict:
        """Ingest a list of pre-loaded documents (e.g., from a git repository).

        Args:
            documents: List of Document objects to ingest
            namespace: Pinecone namespace to store vectors in
            resource_id: Optional resource ID for source linking
            generate_summary: If True, generate an LLM summary of the documents

        Returns:
            Dict with ingestion stats and optional summary
        """
        if not self._initialized:
            self.initialize()

        if not documents:
            return {"documents": 0, "chunks": 0, "vectors_upserted": 0}

        print(f"Ingesting {len(documents)} document(s)")

        # Add resource_id to document metadata if provided
        if resource_id:
            for doc in documents:
                doc.metadata["resource_id"] = resource_id

        # Chunk documents
        print("Chunking documents...")
        chunks = self.chunker.chunk_documents(documents)
        print(f"Created {len(chunks)} chunk(s)")

        if not chunks:
            return {"documents": len(documents), "chunks": 0, "vectors_upserted": 0}

        # Generate embeddings
        print("Generating embeddings...")
        chunk_embeddings = self.embedder.embed_chunks(chunks)
        embeddings = [emb for _, emb in chunk_embeddings]
        print(f"Generated {len(embeddings)} embedding(s)")

        # Store in vector database
        print("Storing in Pinecone...")
        result = self.vectorstore.upsert(chunks, embeddings, namespace=namespace)
        print(f"Upserted {result['upserted_count']} vector(s)")

        output = {
            "documents": len(documents),
            "chunks": len(chunks),
            "vectors_upserted": result["upserted_count"]
        }

        # Generate summary if requested
        if generate_summary and documents:
            print("Generating document summary...")
            # Sample first N files for summary (to avoid token limits)
            sample_docs = documents[:10]
            combined_content = "\n\n---\n\n".join([
                f"File: {doc.source}\n{doc.content[:2000]}"
                for doc in sample_docs
            ])
            summary = generate_document_summary(combined_content[:15000], filename="repository")
            output["summary"] = summary
            print(f"Summary: {summary[:100]}..." if summary else "Summary generation failed")

        return output

    def stats(self) -> dict:
        """Get statistics about the vector store."""
        if not self._initialized:
            self.initialize()
        return self.vectorstore.stats()
