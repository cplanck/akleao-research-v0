"""Embedding module - converts text to vectors using OpenAI."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI, RateLimitError
from .chunker import Chunk


class Embedder:
    """Generates embeddings using OpenAI's API."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "text-embedding-3-small"
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        # Dimensions for different models
        self._dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

    @property
    def dimensions(self) -> int:
        """Return the embedding dimensions for the current model."""
        return self._dimensions.get(self.model, 1536)

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

    def _embed_batch(
        self,
        batch: list[str],
        batch_index: int,
        max_retries: int = 5,
        base_delay: float = 1.0
    ) -> tuple[int, list[list[float]]]:
        """Embed a single batch and return with its index for ordering.

        Includes exponential backoff retry logic for rate limit errors.
        """
        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch
                )
                # Sort by index to maintain order within batch
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return batch_index, [d.embedding for d in sorted_data]
            except RateLimitError as e:
                if attempt == max_retries - 1:
                    raise  # Re-raise on final attempt
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                delay = base_delay * (2 ** attempt)
                print(f"[Embedder] Rate limited, waiting {delay:.1f}s before retry ({attempt + 1}/{max_retries})")
                time.sleep(delay)

    def embed_texts(self, texts: list[str], parallel: bool = True) -> list[list[float]]:
        """Generate embeddings for multiple texts (batched).

        Args:
            texts: List of texts to embed
            parallel: If True, process batches in parallel (faster for large docs)
        """
        if not texts:
            return []

        # OpenAI supports up to 2048 texts per call, but we use 500 for safety
        # to avoid token limits while still being efficient
        batch_size = 500

        # Create batches
        batches = []
        for i in range(0, len(texts), batch_size):
            batches.append((i // batch_size, texts[i:i + batch_size]))

        if not parallel or len(batches) == 1:
            # Sequential processing
            all_embeddings = []
            for batch_idx, batch in batches:
                _, embeddings = self._embed_batch(batch, batch_idx)
                all_embeddings.extend(embeddings)
            return all_embeddings

        # Parallel processing for multiple batches
        all_embeddings = [None] * len(batches)

        # Use up to 5 parallel workers (OpenAI rate limits)
        max_workers = min(5, len(batches))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._embed_batch, batch, idx): idx
                for idx, batch in batches
            }

            for future in as_completed(futures):
                batch_idx, embeddings = future.result()
                all_embeddings[batch_idx] = embeddings

        # Flatten the results maintaining order
        return [emb for batch_embs in all_embeddings for emb in batch_embs]

    def embed_chunks(self, chunks: list[Chunk], parallel: bool = True) -> list[tuple[Chunk, list[float]]]:
        """Generate embeddings for chunks, returning (chunk, embedding) pairs."""
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embed_texts(texts, parallel=parallel)
        return list(zip(chunks, embeddings))
