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
        namespaces: list[str] = None,
        filter: dict = None
    ) -> list[RetrievalResult]:
        """Retrieve relevant chunks for a query.

        Args:
            query: The query text to search for
            top_k: Number of results to return
            namespace: Single namespace to search (deprecated, use namespaces)
            namespaces: List of namespaces to search across
            filter: Metadata filter to apply
        """
        # Embed the query
        query_embedding = self.embedder.embed_text(query)

        # Support both single namespace (backwards compat) and multiple namespaces
        ns_list = namespaces if namespaces else ([namespace] if namespace else [""])

        all_results = []
        k = top_k or self.top_k

        # Query each namespace and combine results
        for ns in ns_list:
            results = self.vectorstore.query(
                embedding=query_embedding,
                top_k=k,
                namespace=ns,
                filter=filter
            )
            all_results.extend(results)

        # Sort by score descending and take top_k
        all_results.sort(key=lambda x: x["score"], reverse=True)
        all_results = all_results[:k]

        # Filter by score threshold and convert to RetrievalResult
        retrieved = []
        for result in all_results:
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
