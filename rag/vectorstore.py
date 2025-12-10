"""Vector store module - handles Pinecone operations."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pinecone import Pinecone, ServerlessSpec
from .chunker import Chunk


class VectorStore:
    """Manages vector storage and retrieval with Pinecone."""

    def __init__(
        self,
        api_key: str,
        index_name: str = "simage-rag",
        dimension: int = 1536,
        metric: str = "cosine"
    ):
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.dimension = dimension
        self.metric = metric
        self._index = None

    def create_index_if_not_exists(self) -> None:
        """Create the Pinecone index if it doesn't exist."""
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric=self.metric,
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1"
                )
            )
            print(f"Created index: {self.index_name}")
        else:
            print(f"Index already exists: {self.index_name}")

    @property
    def index(self):
        """Get or create index connection."""
        if self._index is None:
            self._index = self.pc.Index(self.index_name)
        return self._index

    def _upsert_batch(self, batch: list[dict], namespace: str) -> int:
        """Upsert a single batch and return count."""
        result = self.index.upsert(vectors=batch, namespace=namespace)
        return result.upserted_count

    def upsert(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        namespace: str = "",
        parallel: bool = True
    ) -> dict:
        """Insert or update vectors in the index.

        Args:
            chunks: List of chunks to upsert
            embeddings: List of embeddings corresponding to chunks
            namespace: Pinecone namespace
            parallel: If True, upsert batches in parallel (faster for large docs)
        """
        vectors = []

        for chunk, embedding in zip(chunks, embeddings):
            vectors.append({
                "id": chunk.id,
                "values": embedding,
                "metadata": {
                    "content": chunk.content,
                    "source": chunk.source,
                    "doc_id": chunk.doc_id,
                    "chunk_index": chunk.chunk_index,
                    **chunk.metadata
                }
            })

        # Pinecone recommends batches of 100
        batch_size = 100

        # Create batches
        batches = []
        for i in range(0, len(vectors), batch_size):
            batches.append(vectors[i:i + batch_size])

        if not parallel or len(batches) <= 2:
            # Sequential for small numbers of batches
            total_upserted = 0
            for batch in batches:
                total_upserted += self._upsert_batch(batch, namespace)
            return {"upserted_count": total_upserted}

        # Parallel upserts for large documents
        total_upserted = 0
        max_workers = min(10, len(batches))  # Pinecone can handle more concurrency

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._upsert_batch, batch, namespace)
                for batch in batches
            ]

            for future in as_completed(futures):
                total_upserted += future.result()

        return {"upserted_count": total_upserted}

    def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        namespace: str = "",
        filter: dict = None
    ) -> list[dict]:
        """Query the index for similar vectors."""
        results = self.index.query(
            vector=embedding,
            top_k=top_k,
            include_metadata=True,
            namespace=namespace,
            filter=filter
        )

        return [
            {
                "id": match.id,
                "score": match.score,
                "content": match.metadata.get("content", ""),
                "source": match.metadata.get("source", ""),
                "metadata": match.metadata
            }
            for match in results.matches
        ]

    def delete_by_source(self, source: str, namespace: str = "") -> None:
        """Delete all vectors from a specific source document."""
        # Pinecone requires fetching IDs first for deletion by metadata
        # This is a limitation - for now we'll delete by filter if supported
        self.index.delete(
            filter={"source": {"$eq": source}},
            namespace=namespace
        )

    def stats(self) -> dict:
        """Get index statistics."""
        return self.index.describe_index_stats()
