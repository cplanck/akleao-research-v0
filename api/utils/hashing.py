"""Content hashing utilities for resource deduplication."""

import hashlib


def compute_content_hash(file_path: str = None, content: bytes = None) -> str:
    """Compute SHA256 hash of file or content.

    Args:
        file_path: Path to file to hash (reads in chunks for memory efficiency)
        content: Raw bytes to hash

    Returns:
        64-character hexadecimal SHA256 hash string

    Raises:
        ValueError: If neither file_path nor content is provided
        FileNotFoundError: If file_path doesn't exist
    """
    if file_path is None and content is None:
        raise ValueError("Either file_path or content must be provided")

    sha256 = hashlib.sha256()

    if file_path:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
    elif content:
        sha256.update(content)

    return sha256.hexdigest()


def compute_url_hash(url: str) -> str:
    """Compute hash for URL-based resources.

    For URLs, we hash the normalized URL string itself since the content
    may change over time and we want to identify the same URL resource.

    Args:
        url: The URL string

    Returns:
        64-character hexadecimal SHA256 hash string
    """
    # Normalize URL: lowercase, strip trailing slash
    normalized = url.lower().rstrip('/')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def compute_git_hash(repo_url: str, branch: str = None) -> str:
    """Compute hash for git repository resources.

    Args:
        repo_url: The git repository URL
        branch: Optional branch name (defaults to "default")

    Returns:
        64-character hexadecimal SHA256 hash string
    """
    # Normalize repo URL
    normalized_url = repo_url.lower().rstrip('/').rstrip('.git')
    branch_str = branch or "default"

    # Combine URL and branch
    identifier = f"{normalized_url}:{branch_str}"
    return hashlib.sha256(identifier.encode('utf-8')).hexdigest()
