"""Minimal client for Ollama's local chat API."""
import json
import urllib.error
import urllib.request


def normalize_host(host):
    """Accept Ollama-style hosts ('127.0.0.1:11434', '0.0.0.0') as well as full URLs."""
    host = (host or "").strip().rstrip("/") or "http://127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    if ":" not in host.split("://", 1)[1]:
        host += ":11434"
    return host


class OllamaAPIError(Exception):
    """Raised when the local Ollama API cannot complete a request."""


class OllamaClient:
    def __init__(self, host="http://127.0.0.1:11434"):
        self.host = normalize_host(host)

    def chat(self, **kwargs):
        url = self.host + "/api/chat"
        data = json.dumps(kwargs).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OllamaAPIError(
                f"Ollama returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaAPIError(
                f"Could not get a valid response from Ollama: {exc}"
            ) from exc
