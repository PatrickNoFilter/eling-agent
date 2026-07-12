"""
Pure-python bag-of-words cosine similarity with no external dependencies.
No numpy/scipy/sklearn required.
"""

import collections
import math
import re


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens on non-alphanumeric boundaries."""
    if not isinstance(text, str):
        text = str(text)
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def vectorize(text: str) -> collections.Counter:
    """Convert text to a Bag-of-Words Counter."""
    return collections.Counter(tokenize(text))


def cosine_sim(vec_a: collections.Counter, vec_b: collections.Counter) -> float:
    """Compute cosine similarity between two Counters (no numpy)."""
    # Intersection dot product
    dot_product = 0
    for token in vec_a:
        if token in vec_b:
            dot_product += vec_a[token] * vec_b[token]

    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def top_k(
    query: str, candidates: list, text_fn, k: int = 5, min_score: float = 0.05
) -> list:
    """
    Return the top-k candidates sorted by cosine similarity descending.

    Args:
        query: The search query string.
        candidates: Iterable of items to score.
        text_fn: Callable(item) -> str, returns the text to compare.
        k: Maximum number of results.
        min_score: Minimum similarity score to include.

    Returns:
        List of (item, score) tuples sorted by score descending.
    """
    query_vec = vectorize(query)

    scored = []
    for item in candidates:
        vec = vectorize(text_fn(item))
        score = cosine_sim(query_vec, vec)
        if score >= min_score:
            scored.append((item, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
