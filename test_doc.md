# Simage RAG System Overview

## Purpose
The Simage RAG system is designed to ingest documents, create embeddings, store them in a vector database, and enable intelligent querying using large language models.

## Architecture Components

### Document Ingestion
The system supports multiple document formats:
- PDF files using pypdf
- Microsoft Word documents (.docx) using python-docx
- Markdown files (.md)
- Plain text files (.txt)

### Chunking Strategy
Documents are split into smaller chunks for better retrieval:
- Default chunk size: 500 tokens
- Overlap between chunks: 50 tokens
- Uses tiktoken for accurate token counting

### Vector Storage
We use Pinecone as our vector database because:
- It's fully managed and scalable
- Supports metadata filtering
- Has a generous free tier for prototyping
- Provides fast similarity search

### Embedding Model
OpenAI's text-embedding-3-small model is used for generating embeddings:
- 1536 dimensions
- Good balance of quality and cost
- Fast inference times

### LLM for Generation
Claude (from Anthropic) handles the response generation:
- Uses retrieved context to answer questions
- Cites sources when possible
- Admits when information is not available

## Usage Example

To ingest documents:
```
python main.py ingest /path/to/documents
```

To query:
```
python main.py query "What is the chunking strategy?"
```

## Configuration
All API keys are stored in a .env file:
- OPENAI_API_KEY for embeddings
- ANTHROPIC_API_KEY for Claude
- PINECONE_API_KEY for vector storage
