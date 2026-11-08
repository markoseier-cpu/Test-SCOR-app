"""Indekseerimine ja indeksi kehtivuse kontroll.

Indeks loetakse kehtivaks ainult siis, kui kõik järgmised tingimused on täidetud:
  1. salvestatud PDF-faili SHA-256 räsi = dokumendi identifikaator;
  2. indeksi embedding-mudel = praegu valitud embedding-mudel;
  3. töötlemisseadete räsi (lõigu pikkus, kattuvus, tabelite eraldamine, töötlemise versioonid)
     = praeguste seadete räsi;
  4. vektorifail on olemas ja selle mõõtmed vastavad lõikude arvule.
Muul juhul tuleb indeks uuesti luua.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .chunking import CHUNKING_VERSION, build_chunks
from .pdf_processing import EXTRACTION_VERSION, extract_pages, sha256_file
from .storage import DocumentRecord, Storage


class Embedder(Protocol):
    def embed(self, model: str, texts: list[str]) -> np.ndarray: ...


def processing_settings(embed_model: str, chunk_tokens: int, chunk_overlap: float, extract_tables: bool) -> dict:
    return {
        "embed_model": embed_model,
        "chunk_tokens": int(chunk_tokens),
        "chunk_overlap": round(float(chunk_overlap), 4),
        "extract_tables": bool(extract_tables),
        "chunking_version": CHUNKING_VERSION,
        "extraction_version": EXTRACTION_VERSION,
    }


def settings_hash(settings: dict) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class IndexStatus:
    state: str  # 'ready' | 'missing' | 'stale' | 'broken'
    reasons: list[str] = field(default_factory=list)
    chunk_count: int = 0
    embed_model: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"


def normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class IndexManager:
    def __init__(self, storage: Storage, embedder: Embedder, embed_model: str,
                 chunk_tokens: int, chunk_overlap: float, extract_tables: bool = True,
                 batch_size: int = 16):
        self.storage = storage
        self.embedder = embedder
        self.embed_model = embed_model
        self.chunk_tokens = chunk_tokens
        self.chunk_overlap = chunk_overlap
        self.extract_tables = extract_tables
        self.batch_size = max(1, batch_size)
        self._hash_cache: dict[tuple[str, float, int], str] = {}

    @property
    def current_settings(self) -> dict:
        return processing_settings(self.embed_model, self.chunk_tokens, self.chunk_overlap, self.extract_tables)

    def _file_hash(self, path: Path) -> str:
        st = path.stat()
        key = (str(path), st.st_mtime, st.st_size)
        if key not in self._hash_cache:
            self._hash_cache[key] = sha256_file(path)
        return self._hash_cache[key]

    def status(self, doc: DocumentRecord) -> IndexStatus:
        pdf = Path(doc.pdf_path)
        if not pdf.is_file():
            return IndexStatus("broken", ["Salvestatud PDF-fail puudub andmekaustast. Laadi dokument uuesti üles."])
        if self._file_hash(pdf) != doc.sha256:
            return IndexStatus("broken", ["Salvestatud PDF-faili räsi ei vasta dokumendi räsile (fail on muutunud)."])
        st = self.storage.get_index_state(doc.doc_id)
        if st is None or st.status != "ready":
            return IndexStatus("missing", ["Dokument on indekseerimata."])
        reasons = []
        if st.embed_model != self.embed_model:
            reasons.append(
                f"Indeks on loodud embedding-mudeliga „{st.embed_model}”, valitud on „{self.embed_model}”."
            )
        cur = self.current_settings
        if st.settings_hash != settings_hash(cur):
            changed = [k for k in cur if k != "embed_model" and st.settings.get(k) != cur[k]]
            if changed:
                reasons.append("Töötlemisseaded on muutunud: " + ", ".join(changed) + ".")
            elif not reasons:
                reasons.append("Indeksi seadete räsi ei vasta praegustele seadetele.")
        if reasons:
            return IndexStatus("stale", reasons + ["Indeks tuleb uuesti luua."], st.chunk_count, st.embed_model)
        try:
            self.storage.load_vectors(st)
        except (FileNotFoundError, ValueError) as exc:
            return IndexStatus("broken", [f"Indeksi vektorifail on vigane: {exc}. Indekseeri uuesti."])
        return IndexStatus("ready", [], st.chunk_count, st.embed_model)

    def build(self, doc: DocumentRecord, progress: Callable[[str, float], None] | None = None) -> IndexStatus:
        """Loob dokumendi indeksi (lõigud + vektorid). Olemasolev indeks asendatakse alles õnnestumisel."""
        def report(msg: str, frac: float) -> None:
            if progress:
                progress(msg, max(0.0, min(1.0, frac)))

        pdf = Path(doc.pdf_path)
        if self._file_hash(pdf) != doc.sha256:
            raise ValueError("Salvestatud PDF-faili räsi ei vasta dokumendile. Laadi dokument uuesti üles.")

        pages = None
        if doc.extraction.get("extract_tables") == self.extract_tables and \
                doc.extraction.get("extraction_version") == EXTRACTION_VERSION:
            pages = self.storage.get_pages(doc.doc_id)
        if not pages:
            report("Eraldan teksti uuesti…", 0.0)
            pages = extract_pages(pdf.read_bytes(), self.extract_tables).pages

        report("Jagan teksti lõikudeks…", 0.02)
        chunks = build_chunks(pages, self.chunk_tokens, self.chunk_overlap)
        if not chunks:
            raise ValueError("Dokumendist ei tekkinud ühtegi tekstilõiku – tühja dokumenti ei indekseerita.")

        vectors: list[np.ndarray] = []
        total = len(chunks)
        for start in range(0, total, self.batch_size):
            batch = chunks[start:start + self.batch_size]
            emb = self.embedder.embed(self.embed_model, [c.text for c in batch])
            vectors.append(np.asarray(emb, dtype=np.float32))
            done = min(total, start + len(batch))
            report(f"Loon embedding-vektoreid: {done}/{total} lõiku", 0.05 + 0.93 * done / total)
        matrix = normalize(np.vstack(vectors))

        cur = self.current_settings
        self.storage.replace_index(doc.doc_id, chunks, matrix, self.embed_model, settings_hash(cur), cur)
        report("Indeks salvestatud.", 1.0)
        return self.status(doc)
