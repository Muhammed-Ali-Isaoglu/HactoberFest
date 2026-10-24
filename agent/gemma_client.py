"""Ollama chat client for Gemma. Output is untrusted until it passes schema validation and the dispatcher."""

import httpx


class ModelUnavailable(RuntimeError):
    """Ollama is down, slow, or does not have the configured model."""


class GemmaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def health(self) -> dict:
        try:
            resp = self._client.get("/api/tags", timeout=3.0)
            resp.raise_for_status()
        except httpx.HTTPError:
            return {"ollama": "unreachable", "model": self._model}
        names = {m.get("name") for m in resp.json().get("models", [])}
        return {"ollama": "ok", "model": self._model, "model_present": self._model in names}

    def chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "format": "json",  # ask for JSON; still validated by the caller
            "options": {"temperature": 0},
        }
        try:
            resp = self._client.post("/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelUnavailable(type(exc).__name__) from exc
        return resp.json()["message"]["content"]
