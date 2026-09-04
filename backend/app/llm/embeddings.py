"""Porta EmbeddingProvider: vetores para recuperação e deduplicação semântica.

Implementações:
- OpenRouterEmbeddings — canal API (openai/text-embedding-3-small por padrão), em lotes.
- FakeEmbeddings — determinística (bag-of-words hasheado), para testes sem rede.

`get_provider()` devolve None quando embeddings estão desligados ou sem chave: os
chamadores degradam para o comportamento textual (sem recuperação vetorial).
"""

import hashlib
import logging
import math
import re
import time
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)

BATCH = 64


class EmbeddingProvider(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenRouterEmbeddings:
    def __init__(
        self, api_key: str | None = None, model: str | None = None, dim: int | None = None
    ):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.embedding_model
        self.dim = dim or settings.embedding_dim
        self.base_url = settings.openrouter_base_url

    def _call(self, textos: list[str]) -> list[list[float]]:
        ultimo: Exception | None = None
        for tentativa in range(4):
            try:
                r = httpx.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": textos},
                    timeout=60,
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"status {r.status_code}", request=r.request, response=r
                    )
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                ultimo = e
                time.sleep(1.5 * (tentativa + 1))
        raise RuntimeError(f"embeddings OpenRouter falharam: {ultimo}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        saida: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            lote = [t if t.strip() else " " for t in texts[i : i + BATCH]]
            saida.extend(self._call(lote))
        return saida


class FakeEmbeddings:
    """Bag-of-words hasheado + normalização: textos parecidos → vetores próximos.
    Sem rede, determinístico; só para testes."""

    model = "fake"

    def __init__(self, dim: int | None = None):
        self.dim = dim or settings.embedding_dim

    def _vec(self, texto: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", texto.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_provider() -> EmbeddingProvider | None:
    modo = (settings.embedding_provider or "off").lower()
    if modo == "off":
        return None
    if modo == "fake":
        return FakeEmbeddings()
    if modo == "openrouter":
        if not settings.openrouter_api_key:
            log.warning(
                "EMBEDDING_PROVIDER=openrouter sem OPENROUTER_API_KEY — embeddings desligados"
            )
            return None
        return OpenRouterEmbeddings()
    log.warning("embedding_provider desconhecido: %s — embeddings desligados", modo)
    return None


def text_hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:32]
