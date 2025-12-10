"""Retrieval module - finds relevant chunks for a query."""

from dataclasses import dataclass
from .embeddings import Embedder
from .vectorstore import VectorStore


@dataclass
class RetrievalResult:
    """Represents a retrieved chunk with its relevance score."""
    content: str
    source: str
    score: float
    metadata: dict


class Retriever:
    """Retrieves relevant context for queries."""

    def __init__(
        self,
        embedder: Embedder,
        vectorstore: VectorStore,
        top_k: int = 5,
        score_threshold: float = 0.3
    ):
        self.embedder = embedder
        self.vectorstore = vectorstore
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        namespace: str = "",
        filter: dict = None
    ) -> list[RetrievalResult]:
        """Retrieve relevant chunks for a query."""
        # Embed the query
        query_embedding = self.embedder.embed_text(query)

        # Search vector store
        results = self.vectorstore.query(
            embedding=query_embedding,
            top_k=top_k or self.top_k,
            namespace=namespace,
            filter=filter
        )

        # Filter by score threshold and convert to RetrievalResult
        retrieved = []
        for result in results:
            if result["score"] >= self.score_threshold:
                retrieved.append(RetrievalResult(
                    content=result["content"],
                    source=result["source"],
                    score=result["score"],
                    metadata=result["metadata"]
                ))

        return retrieved

    def format_context(self, results: list[RetrievalResult]) -> str:
        """Format retrieved results as context for the LLM."""
        if not results:
            return "No relevant context found."

        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[Source {i}: {result.source}]\n{result.content}"
            )

        return "\n\n---\n\n".join(context_parts)
