"""Porta LLMProvider (PRD §89): chamadas leves de LLM via OpenRouter (canal API).

O trabalho pesado sobre repositórios NÃO passa por aqui (é da porta
CodeAnalysisEngine/harness). Aqui vivem os agentes leves: tradução de evidence,
Explanation/Review Assistant (Fase 5+).
"""

from typing import Protocol

import httpx

from app.config import settings


class LLMProvider(Protocol):
    def complete(self, *, system: str, user: str, max_tokens: int = 1024) -> str: ...


class OpenRouterProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = (base_url or settings.openrouter_base_url).rstrip("/")

    def complete(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY não configurada no .env")
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def get_provider() -> LLMProvider:
    return OpenRouterProvider()


TRANSLATE_SYSTEM = (
    "Você traduz evidência técnica de sistemas legados para linguagem de negócio, "
    "em português, para leigos (PRD §46). Uma a três frases, sem jargão técnico, sem "
    "código. Descreva O QUE o trecho garante/faz em termos de negócio. Se o trecho for "
    "insuficiente para afirmar algo, diga exatamente: 'Trecho insuficiente para tradução.'"
)


def translate_evidence(excerpt: str, context: str, provider: LLMProvider | None = None) -> str:
    provider = provider or get_provider()
    user = f"Contexto: {context}\n\nTrecho técnico:\n{excerpt[:4000]}"
    return provider.complete(system=TRANSLATE_SYSTEM, user=user, max_tokens=300).strip()
