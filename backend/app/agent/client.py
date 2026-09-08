"""Cliente HTTP do agente para a API `/harness/agent/*`."""

import httpx

AGENT_KEY_HEADER = "X-BSP-Agent-Key"


class AgentApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class UpgradeRequired(AgentApiError):
    """426: o servidor exige uma versão mais nova do agente."""


class AgentClient:
    def __init__(self, api_url: str, api_key: str, timeout: float = 120.0):
        self._http = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={AGENT_KEY_HEADER: api_key},
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict | None = None) -> httpx.Response:
        r = self._http.post(path, json=body or {})
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            if r.status_code == 426:
                raise UpgradeRequired(r.status_code, str(detail))
            raise AgentApiError(r.status_code, str(detail))
        return r

    def register(self, hello: dict) -> dict:
        return self._post("/harness/agent/register", hello).json()

    def claim(self, hello: dict) -> dict | None:
        r = self._post("/harness/agent/claim", hello)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def heartbeat(self, task_id: str) -> dict:
        return self._post(f"/harness/agent/tasks/{task_id}/heartbeat").json()

    def result(self, task_id: str, result: dict, log_text: str | None) -> dict:
        return self._post(
            f"/harness/agent/tasks/{task_id}/result", {"result": result, "log_text": log_text}
        ).json()

    def fail(self, task_id: str, kind: str, detail: str) -> dict:
        return self._post(
            f"/harness/agent/tasks/{task_id}/fail", {"kind": kind, "detail": detail[:4000]}
        ).json()
