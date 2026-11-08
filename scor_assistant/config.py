"""Seadistused.

Väärtused loetakse järjekorras: keskkonnamuutuja > projektikausta `.env` fail > vaikeväärtus.
`.env` faili parsitakse siin ise (lihtne KEY=VALUE vorming), et vältida lisasõltuvust.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    """Vigane seadistus."""


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # eemalda rea lõpu kommentaar
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "jah", "on"}


def is_local_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_ollama_url(url: str, allow_remote: bool = False) -> str:
    """Kontrollib, et Ollama aadress on vaikimisi lokaalne (localhost / loopback)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError(f"Vigane Ollama aadress: {url!r}. Näide: http://127.0.0.1:11434")
    if not allow_remote and not is_local_host(parsed.hostname):
        raise ConfigError(
            f"Ollama aadress {url!r} ei ole lokaalne. Dokumendi sisu ei tohi lahkuda arvutist. "
            "Kasuta http://127.0.0.1:11434 või sea teadlikult SCOR_ALLOW_REMOTE_OLLAMA=true."
        )
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    allow_remote_ollama: bool = False
    llm_model: str = ""
    embed_model: str = "bge-m3"
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    max_upload_mb: int = 100
    chunk_tokens: int = 650
    chunk_overlap: float = 0.15
    top_k: int = 8
    candidate_k: int = 30
    num_ctx: int = 8192
    answer_tokens: int = 1024
    temperature: float = 0.1
    request_timeout: int = 300
    embed_batch_size: int = 16
    extract_tables: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "scor_assistant.sqlite3"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.documents_dir, self.vectors_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: Path | None = None, overrides: dict | None = None) -> Settings:
    env_file = env_file or PROJECT_ROOT / ".env"
    file_values = _read_env_file(env_file)

    def get(name: str, default: str) -> str:
        return os.environ.get(name, file_values.get(name, default))

    try:
        data_dir = Path(get("SCOR_DATA_DIR", str(PROJECT_ROOT / "data")))
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        allow_remote = _bool(get("SCOR_ALLOW_REMOTE_OLLAMA", "false"))
        values = dict(
            ollama_url=validate_ollama_url(get("SCOR_OLLAMA_URL", "http://127.0.0.1:11434"), allow_remote),
            allow_remote_ollama=allow_remote,
            llm_model=get("SCOR_LLM_MODEL", ""),
            embed_model=get("SCOR_EMBED_MODEL", "bge-m3"),
            data_dir=data_dir,
            max_upload_mb=int(get("SCOR_MAX_UPLOAD_MB", "100")),
            chunk_tokens=int(get("SCOR_CHUNK_TOKENS", "650")),
            chunk_overlap=float(get("SCOR_CHUNK_OVERLAP", "0.15")),
            top_k=int(get("SCOR_TOP_K", "8")),
            candidate_k=int(get("SCOR_CANDIDATE_K", "30")),
            num_ctx=int(get("SCOR_NUM_CTX", "8192")),
            answer_tokens=int(get("SCOR_ANSWER_TOKENS", "1024")),
            temperature=float(get("SCOR_TEMPERATURE", "0.1")),
            request_timeout=int(get("SCOR_REQUEST_TIMEOUT", "300")),
            embed_batch_size=int(get("SCOR_EMBED_BATCH_SIZE", "16")),
            extract_tables=_bool(get("SCOR_EXTRACT_TABLES", "true")),
        )
    except ValueError as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"Vigane arvuline seadistus: {exc}") from exc
    if overrides:
        values.update(overrides)
    s = Settings(**values)
    if not 100 <= s.chunk_tokens <= 2000:
        raise ConfigError("SCOR_CHUNK_TOKENS peab olema vahemikus 100–2000.")
    if not 0 <= s.chunk_overlap < 0.5:
        raise ConfigError("SCOR_CHUNK_OVERLAP peab olema vahemikus 0–0.5 (nt 0.15).")
    if s.max_upload_mb <= 0 or s.top_k <= 0:
        raise ConfigError("SCOR_MAX_UPLOAD_MB ja SCOR_TOP_K peavad olema positiivsed.")
    return s
