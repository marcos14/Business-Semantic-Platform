"""Cliente HTTP autenticado da API BSP, usado pelas tools MCP e pelo assistente.

Autentica por token pronto (``BSP_TOKEN`` ou o bearer do usuário logado, no endpoint
``/assistant/chat``) ou por login com e-mail/senha (``BSP_EMAIL``/``BSP_PASSWORD``); neste
caso, um 401 dispara um novo login uma única vez (o JWT expira em 24h).
"""

from __future__ import annotations

import threading
from typing import Any

import httpx


class BspApiError(Exception):
    """Erro devolvido pela API (status + detail), já legível para o agente."""

    def __init__(self, status: int, detail: Any, method: str = "", path: str = ""):
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path
        super().__init__(f"{method} {path} -> HTTP {status}: {detail}")


class BspClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._email = email
        self._password = password
        self._lock = threading.Lock()
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    # ---------- auth ----------

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def login(self) -> str:
        if not (self._email and self._password):
            raise BspApiError(
                401,
                "Sem credenciais: defina BSP_TOKEN ou BSP_EMAIL/BSP_PASSWORD no .env",
                "POST",
                "/auth/login",
            )
        r = self._http.post("/auth/login", json={"email": self._email, "password": self._password})
        if r.status_code != 200:
            raise BspApiError(r.status_code, _detail(r), "POST", "/auth/login")
        self._token = r.json()["access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        with self._lock:
            if not self._token:
                self.login()
            return {"Authorization": f"Bearer {self._token}"}

    # ---------- requests ----------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        _retry: bool = True,
    ) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        r = self._http.request(method, path, params=clean, json=json, headers=self._headers())
        if r.status_code == 401 and _retry and self._email and self._password:
            with self._lock:
                self._token = None
            return self.request(method, path, params=params, json=json, _retry=False)
        if r.status_code >= 400:
            raise BspApiError(r.status_code, _detail(r), method, path)
        if r.status_code == 204 or not r.content:
            return {"ok": True}
        ctype = r.headers.get("content-type", "")
        return r.json() if "json" in ctype else r.text

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self.request("POST", path, params=params, json=json)

    def patch(self, path: str, json: Any = None) -> Any:
        return self.request("PATCH", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def close(self) -> None:
        self._http.close()


def _detail(r: httpx.Response) -> Any:
    try:
        body = r.json()
    except ValueError:
        return r.text[:500]
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body


def client_from_settings() -> BspClient:
    """Cliente configurado pelo .env (BSP_API_URL, BSP_TOKEN ou BSP_EMAIL/BSP_PASSWORD)."""
    from app.config import settings

    return BspClient(
        settings.bsp_api_url,
        token=settings.bsp_token or None,
        email=settings.bsp_email or None,
        password=settings.bsp_password or None,
    )
