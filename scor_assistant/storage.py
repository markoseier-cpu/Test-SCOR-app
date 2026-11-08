"""Lokaalne salvestus: SQLite (dokumendid, leheküljed, lõigud, indeksi olek) ja NumPy (vektorid).

Kõik andmed on kaustas `data/` (seadistus SCOR_DATA_DIR), mis on Gitist välistatud.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,          -- = SHA-256 räsi
    filename    TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    page_count  INTEGER NOT NULL,
    pdf_path    TEXT NOT NULL,
    extraction  TEXT NOT NULL,             -- JSON: tühjad lehed, tabelid, hoiatused, versioon
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_no     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    has_table   INTEGER NOT NULL DEFAULT 0,
    headings    TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (doc_id, page_no)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,      -- <doc_id[:12]>-p<page>-c<index>
    doc_id          TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,      -- = rea number vektorimaatriksis
    page_no         INTEGER NOT NULL,
    section         TEXT,
    text            TEXT NOT NULL,
    token_estimate  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, chunk_index);
CREATE TABLE IF NOT EXISTS index_state (
    doc_id         TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    status         TEXT NOT NULL,          -- 'building' | 'ready'
    embed_model    TEXT NOT NULL,
    settings_hash  TEXT NOT NULL,
    settings_json  TEXT NOT NULL,
    vector_file    TEXT NOT NULL,
    dim            INTEGER NOT NULL,
    chunk_count    INTEGER NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class DocumentRecord:
    doc_id: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    pdf_path: str
    extraction: dict
    created_at: float


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_index: int
    page_no: int
    section: str | None
    text: str
    token_estimate: int
    filename: str = ""


@dataclass
class IndexState:
    doc_id: str
    status: str
    embed_model: str
    settings_hash: str
    settings: dict
    vector_file: str
    dim: int
    chunk_count: int
    updated_at: float


class Storage:
    def __init__(self, db_path: Path, vectors_dir: Path, documents_dir: Path):
        self.db_path = Path(db_path)
        self.vectors_dir = Path(vectors_dir)
        self.documents_dir = Path(documents_dir)
        for d in (self.db_path.parent, self.vectors_dir, self.documents_dir):
            d.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- dokumendid ----------
    def save_document(self, filename: str, sha256: str, data: bytes, extraction_result,
                      extract_tables: bool = True) -> DocumentRecord:
        from .pdf_processing import EXTRACTION_VERSION

        pdf_path = self.documents_dir / f"{sha256}.pdf"
        if not pdf_path.exists():
            tmp = pdf_path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, pdf_path)
        meta = {
            "empty_pages": extraction_result.empty_pages,
            "table_pages": extraction_result.table_pages,
            "toc_available": extraction_result.toc_available,
            "warnings": extraction_result.warnings,
            "total_chars": extraction_result.total_chars,
            "extract_tables": bool(extract_tables),
            "extraction_version": EXTRACTION_VERSION,
        }
        rec = DocumentRecord(
            doc_id=sha256,
            filename=filename,
            sha256=sha256,
            size_bytes=len(data),
            page_count=extraction_result.page_count,
            pdf_path=str(pdf_path),
            extraction=meta,
            created_at=time.time(),
        )
        with self._conn() as c:
            c.execute("DELETE FROM documents WHERE doc_id = ?", (sha256,))
            c.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (rec.doc_id, rec.filename, rec.sha256, rec.size_bytes, rec.page_count,
                 rec.pdf_path, json.dumps(meta, ensure_ascii=False), rec.created_at),
            )
            c.executemany(
                "INSERT INTO pages VALUES (?,?,?,?,?)",
                [(sha256, p.page_no, p.text, int(p.has_table), json.dumps(p.headings, ensure_ascii=False))
                 for p in extraction_result.pages],
            )
        return rec

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not r:
            return None
        return DocumentRecord(
            doc_id=r["doc_id"], filename=r["filename"], sha256=r["sha256"], size_bytes=r["size_bytes"],
            page_count=r["page_count"], pdf_path=r["pdf_path"], extraction=json.loads(r["extraction"]),
            created_at=r["created_at"],
        )

    def list_documents(self) -> list[DocumentRecord]:
        with self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT doc_id FROM documents ORDER BY created_at DESC")]
        return [d for d in (self.get_document(i) for i in ids) if d]

    def get_pages(self, doc_id: str):
        from .pdf_processing import PageText

        with self._conn() as c:
            rows = c.execute(
                "SELECT page_no, text, has_table, headings FROM pages WHERE doc_id = ? ORDER BY page_no",
                (doc_id,),
            ).fetchall()
        return [PageText(page_no=r[0], text=r[1], has_table=bool(r[2]), headings=json.loads(r[3])) for r in rows]

    def delete_document(self, doc_id: str) -> None:
        doc = self.get_document(doc_id)
        state = self.get_index_state(doc_id)
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM index_state WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            if self.get_app_state("active_doc", conn=c) == doc_id:
                c.execute("DELETE FROM app_state WHERE key = 'active_doc'")
        if state:
            Path(state.vector_file).unlink(missing_ok=True)
        for f in self.vectors_dir.glob(f"{doc_id}_*.npy"):
            f.unlink(missing_ok=True)
        if doc:
            Path(doc.pdf_path).unlink(missing_ok=True)

    # ---------- indeks ----------
    def replace_index(self, doc_id: str, chunks, vectors: np.ndarray, embed_model: str,
                      settings_hash: str, settings: dict) -> IndexState:
        if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
            raise ValueError("Vektorite arv ei vasta lõikude arvule.")
        old = self.get_index_state(doc_id)
        vector_file = self.vectors_dir / f"{doc_id}_{settings_hash}.npy"
        tmp = vector_file.with_name(vector_file.stem + ".tmp.npy")
        np.save(tmp, vectors.astype(np.float32))
        os.replace(tmp, vector_file)
        state = IndexState(
            doc_id=doc_id, status="ready", embed_model=embed_model, settings_hash=settings_hash,
            settings=settings, vector_file=str(vector_file), dim=int(vectors.shape[1]),
            chunk_count=len(chunks), updated_at=time.time(),
        )
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            c.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                [(make_chunk_id(doc_id, ch.page_no, ch.chunk_index), doc_id, ch.chunk_index, ch.page_no,
                  ch.section, ch.text, ch.token_estimate) for ch in chunks],
            )
            c.execute("DELETE FROM index_state WHERE doc_id = ?", (doc_id,))
            c.execute(
                "INSERT INTO index_state VALUES (?,?,?,?,?,?,?,?,?)",
                (doc_id, state.status, embed_model, settings_hash, json.dumps(settings, ensure_ascii=False),
                 state.vector_file, state.dim, state.chunk_count, state.updated_at),
            )
        if old and old.vector_file != state.vector_file:
            Path(old.vector_file).unlink(missing_ok=True)
        return state

    def get_index_state(self, doc_id: str) -> IndexState | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM index_state WHERE doc_id = ?", (doc_id,)).fetchone()
        if not r:
            return None
        return IndexState(
            doc_id=r["doc_id"], status=r["status"], embed_model=r["embed_model"],
            settings_hash=r["settings_hash"], settings=json.loads(r["settings_json"]),
            vector_file=r["vector_file"], dim=r["dim"], chunk_count=r["chunk_count"],
            updated_at=r["updated_at"],
        )

    def get_chunks(self, doc_id: str) -> list[ChunkRecord]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.*, d.filename FROM chunks c JOIN documents d ON d.doc_id = c.doc_id "
                "WHERE c.doc_id = ? ORDER BY c.chunk_index",
                (doc_id,),
            ).fetchall()
        return [
            ChunkRecord(chunk_id=r["chunk_id"], doc_id=r["doc_id"], chunk_index=r["chunk_index"],
                        page_no=r["page_no"], section=r["section"], text=r["text"],
                        token_estimate=r["token_estimate"], filename=r["filename"])
            for r in rows
        ]

    def load_vectors(self, state: IndexState) -> np.ndarray:
        path = Path(state.vector_file)
        if not path.is_file():
            raise FileNotFoundError(f"Vektorifail puudub: {path}")
        vec = np.load(path, allow_pickle=False)
        if vec.shape != (state.chunk_count, state.dim):
            raise ValueError("Vektorifaili mõõtmed ei vasta indeksi olekule.")
        return vec

    # ---------- rakenduse olek ----------
    def get_app_state(self, key: str, conn=None) -> str | None:
        if conn is not None:
            r = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
            return r[0] if r else None
        with self._conn() as c:
            r = c.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def set_app_state(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)", (key, value))


def make_chunk_id(doc_id: str, page_no: int, chunk_index: int) -> str:
    return f"{doc_id[:12]}-p{page_no}-c{chunk_index}"
