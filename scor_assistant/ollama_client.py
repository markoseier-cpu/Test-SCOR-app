"""Kohalik Ollama HTTP-klient (ainult `requests`, ilma pilveteenusteta).

Kasutatavad Ollama API otspunktid (https://github.com/ollama/ollama/blob/main/docs/api.md):
  GET  /api/version  – kas server töötab
  GET  /api/tags     – paigaldatud mudelid
  POST /api/embed    – embedding-vektorid
  POST /api/chat     – vestlusvastus (voogedastusega)
"""

from __future__ import annotations

import json
from typing import Iterator

import numpy as np
import requests

from .config import validate_ollama_url

EMBED_NAME_HINTS = ("embed", "bge", "e5", "minilm", "arctic", "gte", "nomic", "mxbai", "paraphrase", "granite-embedding")
RECOMMENDED_EMBED = "bge-m3"
RECOMMENDED_LLMS = ("qwen2.5:7b", "gemma3:4b", "llama3.1:8b")


class OllamaError(Exception):
    """Üldine Ollama viga (sõnum on kasutajale mõeldud)."""


class OllamaUnavailable(OllamaError):
    pass


class OllamaModelMissing(OllamaError):
    pass


class OllamaTimeout(OllamaError):
    pass


def looks_like_embedding_model(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in EMBED_NAME_HINTS)


class OllamaClient:
    def __init__(self, base_url: str, timeout: int = 300, allow_remote: bool = False):
        self.base_url = validate_ollama_url(base_url, allow_remote)
        self.timeout = timeout
        self.session = requests.Session()
        # Ära kasuta süsteemi HTTP(S)_PROXY seadeid: liiklus peab jääma localhosti.
        self.session.trust_env = False

    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle_error(self, resp: requests.Response, model: str | None) -> None:
        if resp.status_code < 400:
            return
        try:
            msg = resp.json().get("error", resp.text)
        except ValueError:
            msg = resp.text
        if resp.status_code == 404 or "not found" in str(msg).lower():
            raise OllamaModelMissing(
                f"Mudelit „{model}” ei ole Ollamas paigaldatud. Paigalda see käsuga: ollama pull {model}"
            )
        if "does not support" in str(msg).lower():
            raise OllamaError(f"Mudel „{model}” ei toeta seda toimingut: {msg}")
        raise OllamaError(f"Ollama viga (HTTP {resp.status_code}): {msg}")

    def _request(self, method: str, path: str, model: str | None = None, timeout=None, **kw):
        try:
            resp = self.session.request(method, self._url(path), timeout=timeout or (5, self.timeout), **kw)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(
                f"Ollamaga ei saa ühendust aadressil {self.base_url}. Kontrolli, et Ollama on "
                "paigaldatud ja töötab (Windowsis tegumiriba ikoon või käsk `ollama serve`)."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeout(
                f"Ollama ei vastanud {self.timeout} sekundi jooksul. Mudel võib laadida või olla selle "
                "arvuti jaoks liiga suur. Proovi uuesti, vali väiksem mudel või suurenda "
                "SCOR_REQUEST_TIMEOUT väärtust."
            ) from exc
        self._handle_error(resp, model)
        return resp

    # ------------------------------------------------------------------
    def version(self) -> str:
        return self._request("GET", "/api/version", timeout=(3, 5)).json().get("version", "?")

    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/tags", timeout=(3, 10)).json()
        return sorted(m.get("name") or m.get("model") for m in data.get("models", []))

    def ensure_model(self, model: str) -> None:
        if not model:
            raise OllamaModelMissing("Mudel on valimata. Vali külgpaneelilt kohalik mudel.")
        names = self.list_models()
        base = {n.split(":")[0] for n in names if n.endswith(":latest")}
        if model not in names and model not in base:
            raise OllamaModelMissing(
                f"Mudelit „{model}” ei ole Ollamas paigaldatud. Paigalda see käsuga: ollama pull {model}"
            )

    def embed(self, model: str, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        resp = self._request("POST", "/api/embed", model=model, json={"model": model, "input": texts})
        emb = resp.json().get("embeddings")
        if not emb or len(emb) != len(texts):
            raise OllamaError(
                f"Mudel „{model}” ei tagastanud embedding-vektoreid. Kas see on embedding-mudel?"
            )
        return np.asarray(emb, dtype=np.float32)

    def chat(self, model: str, messages: list[dict], num_ctx: int, num_predict: int,
             temperature: float = 0.1) -> str:
        return "".join(self.chat_stream(model, messages, num_ctx, num_predict, temperature))

    def chat_stream(self, model: str, messages: list[dict], num_ctx: int, num_predict: int,
                    temperature: float = 0.1) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature},
        }
        resp = self._request("POST", "/api/chat", model=model, json=payload, stream=True)
        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                obj = json.loads(line)
                if "error" in obj:
                    raise OllamaError(f"Ollama viga: {obj['error']}")
                piece = obj.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if obj.get("done"):
                    break
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeout(
                f"Vastuse genereerimine aegus ({self.timeout} s). Proovi väiksemat mudelit või suurenda "
                "SCOR_REQUEST_TIMEOUT väärtust."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable("Ühendus Ollamaga katkes vastuse genereerimise ajal.") from exc
        finally:
            resp.close()
