"""Testide abivahendid.

NB! Kõik testid kasutavad SÜNTEETILIST testdokumenti. Selle sisu (protsessikoodid XQ…, mõõdikud
jne) on välja mõeldud ainult tehniliseks testimiseks ega ole SCOR 11 sisu.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scor_assistant.storage import Storage  # noqa: E402

SYNTH_BANNER = "SÜNTEETILINE TESTDOKUMENT - EI OLE SCOR 11 SISU"

SYNTH_PAGES = [
    # PDF lk 1
    ("Sissejuhatus",
     "See on tehniline testdokument. Kirjeldatakse väljamõeldud protsessiraamistikku TESTFRAME. "
     "Raamistikus on kolm põhiprotsessi: Alpha, Beta ja Gamma."),
    # PDF lk 2
    ("Protsess Alpha",
     "Protsess Alpha (kood XQ1) hõlmab varude kavandamist. Alamprotsess XQ1.21 kirjeldab "
     "tarnijate hindamist ja ei ole sama mis XQ1.2."),
    # PDF lk 3
    ("Protsess XQ1.2",
     "Alamprotsess XQ1.2 Validate Widget Supply tähendab vidinate tarne kinnitamist enne tootmist. "
     "Mõõdik WCT (Widget Cycle Time) mõõdab tsükliaega päevades."),
    # PDF lk 4 – tühi lehekülg
    (None, ""),
    # PDF lk 5
    ("Mõõdikud",
     "Mõõdik QZR.7 Quality Zeta Ratio on defektideta tarnete osakaal. Lühend OTIFZ tähistab "
     "testmõõdikut On Time In Full Zeta."),
]


def make_pdf(path: Path, pages=SYNTH_PAGES) -> Path:
    doc = fitz.open()
    for heading, body in pages:
        page = doc.new_page(width=595, height=842)
        if heading is not None:
            page.insert_text((50, 50), SYNTH_BANNER, fontsize=8)
            page.insert_text((50, 90), heading, fontsize=18)
            rect = fitz.Rect(50, 110, 545, 800)
            page.insert_textbox(rect, body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


class FakeEmbedder:
    """Deterministlik bag-of-words räsi-embedding testideks (ei vaja Ollamat)."""

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.calls = 0
        self.texts_embedded = 0

    def embed(self, model: str, texts: list[str]) -> np.ndarray:
        self.calls += 1
        self.texts_embedded += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"\w+", t.lower()):
                h = int(hashlib.md5((model + w).encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
        return out


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.messages = None

    def chat_stream(self, model, messages, num_ctx, num_predict, temperature=0.1):
        self.messages = messages
        yield from [self.reply[: len(self.reply) // 2], self.reply[len(self.reply) // 2:]]


@pytest.fixture
def synthetic_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "synthetic_test_document.pdf")


@pytest.fixture
def storage(tmp_path) -> Storage:
    d = tmp_path / "data"
    return Storage(d / "db.sqlite3", d / "vectors", d / "documents")
