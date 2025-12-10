"""RAG Pipeline - orchestrates the full ingestion and query flow."""

import os
from pathlib import Path
from dotenv import load_dotenv

from .ingest import DocumentLoader, Document
from .chunker import Chunker, Chunk
from .embeddings import Embedder
from .vectorstore import VectorStore
from .retriever import Retriever, RetrievalResult
from .llm import LLM


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
        resource_id: str = None
    ) -> dict:
        """Ingest documents from a file or directory."""
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

        return {
            "documents": len(documents),
            "chunks": len(chunks),
            "vectors_upserted": result["upserted_count"]
        }

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
        resource_id: str = None
    ) -> dict:
        """Ingest content from a URL (PDF, webpage, etc.)."""
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

        return {
            "url": url,
            "doc_type": document.doc_type,
            "chunks": len(chunks),
            "vectors_upserted": result["upserted_count"]
        }

    def stats(self) -> dict:
        """Get statistics about the vector store."""
        if not self._initialized:
            self.initialize()
        return self.vectorstore.stats()
