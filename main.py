#!/usr/bin/env python3
"""CLI for the RAG pipeline."""

import argparse
import sys
from pathlib import Path
from rag import RAGPipeline


def cmd_ingest(args):
    """Ingest documents into the RAG system."""
    pipeline = RAGPipeline()
    result = pipeline.ingest(args.path, namespace=args.namespace)

    print("\n✓ Ingestion complete:")
    print(f"  Documents: {result['documents']}")
    print(f"  Chunks: {result['chunks']}")
    print(f"  Vectors stored: {result['vectors_upserted']}")


def cmd_query(args):
    """Query the RAG system."""
    pipeline = RAGPipeline()

    if args.sources:
        result = pipeline.query(
            args.question,
            top_k=args.top_k,
            namespace=args.namespace,
            return_sources=True
        )
        print("\nAnswer:")
        print(result["answer"])
        print("\n--- Sources ---")
        for i, source in enumerate(result["sources"], 1):
            print(f"\n[{i}] {source['source']} (score: {source['score']:.3f})")
            print(f"    {source['content']}")
    else:
        answer = pipeline.query(
            args.question,
            top_k=args.top_k,
            namespace=args.namespace
        )
        print("\n" + answer)


def cmd_stats(args):
    """Show vector store statistics."""
    pipeline = RAGPipeline()
    stats = pipeline.stats()
    print("\nVector Store Stats:")
    print(f"  Total vectors: {stats.get('total_vector_count', 'N/A')}")
    if 'namespaces' in stats:
        print("  Namespaces:")
        for ns, info in stats['namespaces'].items():
            ns_name = ns if ns else "(default)"
            print(f"    {ns_name}: {info.get('vector_count', 0)} vectors")


def cmd_interactive(args):
    """Start interactive query mode."""
    pipeline = RAGPipeline()
    pipeline.initialize()

    print("RAG Interactive Mode")
    print("Type 'quit' or 'exit' to stop, 'sources' to toggle source display")
    print("-" * 40)

    show_sources = False

    while True:
        try:
            question = input("\nQuestion: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue

        if question.lower() in ('quit', 'exit'):
            print("Goodbye!")
            break

        if question.lower() == 'sources':
            show_sources = not show_sources
            print(f"Source display: {'ON' if show_sources else 'OFF'}")
            continue

        result = pipeline.query(
            question,
            top_k=args.top_k,
            namespace=args.namespace,
            return_sources=show_sources
        )

        if show_sources:
            print("\nAnswer:")
            print(result["answer"])
            if result["sources"]:
                print("\n--- Sources ---")
                for i, source in enumerate(result["sources"], 1):
                    print(f"[{i}] {source['source']} (score: {source['score']:.3f})")
        else:
            print("\n" + result)


def main():
    parser = argparse.ArgumentParser(
        description="RAG Pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents")
    ingest_parser.add_argument("path", type=Path, help="File or directory to ingest")
    ingest_parser.add_argument("--namespace", "-n", default="", help="Pinecone namespace")
    ingest_parser.set_defaults(func=cmd_ingest)

    # Query command
    query_parser = subparsers.add_parser("query", help="Query the system")
    query_parser.add_argument("question", help="Question to ask")
    query_parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of chunks to retrieve")
    query_parser.add_argument("--namespace", "-n", default="", help="Pinecone namespace")
    query_parser.add_argument("--sources", "-s", action="store_true", help="Show sources")
    query_parser.set_defaults(func=cmd_query)

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show vector store stats")
    stats_parser.set_defaults(func=cmd_stats)

    # Interactive command
    interactive_parser = subparsers.add_parser("interactive", help="Interactive query mode")
    interactive_parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of chunks to retrieve")
    interactive_parser.add_argument("--namespace", "-n", default="", help="Pinecone namespace")
    interactive_parser.set_defaults(func=cmd_interactive)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
