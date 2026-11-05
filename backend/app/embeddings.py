from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache

from .config import get_settings

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder:
    name = "base"
    dim = 384

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class HashEmbedder(Embedder):
    """Deterministic offline fallback. Lexical, not truly semantic."""

    name = "hash"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = TOKEN_RE.findall((text or "").lower())
        features: list[str] = []
        features.extend(tokens)
        features.extend(f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False))
        for token in tokens:
            if len(token) >= 4:
                features.extend(token[i : i + 3] for i in range(len(token) - 2))
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class FastEmbedder(Embedder):
    name = "fastembed"

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        logger.info("loading embedding model %s (first run may download weights)", model_name)
        self.model = TextEmbedding(model_name=model_name)
        self.model_name = model_name
        # bge-small is 384; infer from a probe.
        probe = next(iter(self.model.embed(["dimension probe"])))
        self.dim = len(probe)
        self.name = f"fastembed:{model_name}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = []
        for vector in self.model.embed(texts):
            values = [float(item) for item in vector]
            norm = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / norm for value in values])
        return vectors


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    provider = settings.embedding_provider.lower()
    if provider in {"fastembed", "auto"}:
        try:
            return FastEmbedder(settings.embedding_model)
        except Exception as exc:
            if provider == "fastembed":
                raise RuntimeError(f"FastEmbed could not be initialized: {exc}") from exc
            logger.warning("FastEmbed unavailable (%s); using deterministic hash embeddings", exc)
    return HashEmbedder(settings.embedding_dim)


def reset_embedder() -> None:
    get_embedder.cache_clear()


def embed_provider_name() -> str:
    try:
        return get_embedder().name
    except Exception:
        return "unavailable"


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left)) or 1.0
    norm_right = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (norm_left * norm_right)
