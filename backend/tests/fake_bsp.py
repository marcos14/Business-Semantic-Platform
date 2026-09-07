"""Cliente BSP falso para testar tools e agente sem API nem banco."""

from __future__ import annotations

from typing import Any


class FakeClient:
    """Responde por rota: ``routes[path]`` ou ``routes[(method, path)]``; exceções são
    levantadas; sem rota devolve ``{}``. Guarda cada chamada em ``calls``."""

    base_url = "http://fake"

    def __init__(self, routes: dict | None = None):
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict, Any]] = []

    def _do(self, method: str, path: str, params: dict | None = None, json: Any = None) -> Any:
        self.calls.append((method, path, params or {}, json))
        value = self.routes.get((method, path), self.routes.get(path, {}))
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, path: str, **params: Any) -> Any:
        return self._do("GET", path, params)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self._do("POST", path, params, json)

    def patch(self, path: str, json: Any = None) -> Any:
        return self._do("PATCH", path, None, json)

    def delete(self, path: str) -> Any:
        return self._do("DELETE", path)

    def close(self) -> None:
        pass

    def paths(self, method: str | None = None) -> list[str]:
        return [p for m, p, _, _ in self.calls if method is None or m == method]
