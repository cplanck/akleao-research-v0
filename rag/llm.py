"""LLM module - generates responses using Claude or OpenAI."""

from typing import Iterator
from .retriever import RetrievalResult


class LLM:
    """Generates responses using Claude (Anthropic) or GPT (OpenAI)."""

    DEFAULT_SYSTEM_PROMPT = """You are a helpful assistant. Answer questions directly and concisely.

If context is provided and relevant to the question, use it to inform your answer. If the question is unrelated to the context (like greetings or general questions), just respond naturally without referencing the context at all.

Never say things like "I see you have context about..." or "Based on the provided information..." - just answer the question."""

    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        system_prompt: str = None,
        max_tokens: int = 1024
    ):
        self.provider = provider.lower()
        self.model = model
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.max_tokens = max_tokens
        self.api_key = api_key

        if self.provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        else:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)

    def generate(
        self,
        query: str,
        context: str,
        system_prompt: str = None
    ) -> str:
        """Generate a response given a query and context."""
        user_message = f"""Context:
{context}

Question: {query}"""

        system = system_prompt or self.system_prompt

        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            return response.content[0].text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message}
                ]
            )
            return response.choices[0].message.content

    def generate_with_results(
        self,
        query: str,
        results: list[RetrievalResult],
        system_prompt: str = None
    ) -> str:
        """Generate a response from RetrievalResults directly."""
        if not results:
            return "I couldn't find any relevant information to answer your question."

        # Format context from results
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[Source {i}: {result.source}]\n{result.content}"
            )

        context = "\n\n---\n\n".join(context_parts)

        return self.generate(query, context, system_prompt)

    def generate_stream(
        self,
        query: str,
        context: str,
        system_prompt: str = None
    ) -> Iterator[str]:
        """Generate a streaming response given a query and context."""
        user_message = f"""Context:
{context}

Question: {query}"""

        system = system_prompt or self.system_prompt

        if self.provider == "anthropic":
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            ) as stream:
                for text in stream.text_stream:
                    yield text
        else:
            stream = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message}
                ],
                stream=True
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    def generate_stream_with_results(
        self,
        query: str,
        results: list[RetrievalResult],
        system_prompt: str = None
    ) -> Iterator[str]:
        """Generate a streaming response from RetrievalResults directly."""
        if not results:
            yield "I couldn't find any relevant information to answer your question."
            return

        # Format context from results
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[Source {i}: {result.source}]\n{result.content}"
            )

        context = "\n\n---\n\n".join(context_parts)

        yield from self.generate_stream(query, context, system_prompt)
