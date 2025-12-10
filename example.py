#!/usr/bin/env python3
"""Example usage of the RAG pipeline as a library."""

from rag import RAGPipeline

# Initialize the pipeline (reads API keys from .env or environment)
pipeline = RAGPipeline(
    chunk_size=500,      # tokens per chunk
    chunk_overlap=50,    # overlap between chunks
)

# Initialize (creates Pinecone index if needed)
pipeline.initialize()

# --- Ingest documents ---
# Single file
# result = pipeline.ingest("path/to/document.pdf")

# Directory of documents
# result = pipeline.ingest("path/to/documents/")

# With a namespace (useful for multi-tenant or organizing by project)
# result = pipeline.ingest("docs/", namespace="project-alpha")


# --- Query ---
# Simple query
# answer = pipeline.query("What is the main topic of the document?")
# print(answer)

# Query with sources
# result = pipeline.query(
#     "What are the key findings?",
#     top_k=5,               # number of chunks to retrieve
#     return_sources=True    # include source information
# )
# print(result["answer"])
# for source in result["sources"]:
#     print(f"- {source['source']} (score: {source['score']:.3f})")


# --- Using individual components ---
from rag import DocumentLoader, Chunker, Embedder, VectorStore, Retriever, LLM

# Load a document
loader = DocumentLoader()
# docs = loader.load("example.pdf")

# Chunk it
chunker = Chunker(chunk_size=500, chunk_overlap=50)
# chunks = chunker.chunk_documents(docs)

# The pipeline handles all of this for you, but you can use
# components individually for custom workflows.


if __name__ == "__main__":
    print("RAG Pipeline Example")
    print("-" * 40)
    print()
    print("Setup:")
    print("1. Copy .env.example to .env")
    print("2. Add your API keys to .env")
    print("3. Install dependencies: pip install -e .")
    print()
    print("CLI Usage:")
    print("  python main.py ingest /path/to/docs")
    print("  python main.py query 'What is this about?'")
    print("  python main.py interactive")
    print("  python main.py stats")
    print()
    print("Library Usage:")
    print("  See the commented examples in this file")
