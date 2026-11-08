"""Kasutajaliidese käivitumise ja töövoo test Streamliti AppTestiga.

Kasutab sünteetilist dokumenti ja võlts-Ollama serverit (tests/fake_ollama.py). See kontrollib
tehnilist ühendust, MITTE päris keelemudeli vastuste kvaliteeti.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import fake_ollama
from conftest import FakeEmbedder, make_pdf
from scor_assistant.indexing import IndexManager
from scor_assistant.pdf_processing import extract_pages, sha256_bytes
from scor_assistant.storage import Storage

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("SCOR_DATA_DIR", str(data))
    monkeypatch.setenv("SCOR_LLM_MODEL", "fake-llm")
    monkeypatch.setenv("SCOR_EMBED_MODEL", "fake-embed")
    return data


def _run(timeout=60):
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.run()
    return at


def test_ui_starts_without_ollama(env, monkeypatch):
    monkeypatch.setenv("SCOR_OLLAMA_URL", "http://127.0.0.1:9")  # mitte keegi ei kuula
    at = _run()
    assert not at.exception
    assert at.title[0].value == "SCOR 11 dokumendiassistent"
    assert any("Ollamaga ei saa ühendust" in e.value for e in at.sidebar.error)
    labels = [b.label for b in at.sidebar.button]
    assert "Tühjenda vestlus" in labels


def test_ui_answers_with_verified_citations(env, monkeypatch, tmp_path):
    srv, url = fake_ollama.start()
    try:
        monkeypatch.setenv("SCOR_OLLAMA_URL", url)
        storage = Storage(env / "scor_assistant.sqlite3", env / "vectors", env / "documents")
        pdf = make_pdf(tmp_path / "synthetic_test_document.pdf")
        data = pdf.read_bytes()
        doc = storage.save_document(pdf.name, sha256_bytes(data), data, extract_pages(data))
        storage.set_app_state("active_doc", doc.doc_id)
        IndexManager(storage, FakeEmbedder(), "fake-embed:latest", 650, 0.15).build(doc)

        at = _run()
        assert not at.exception
        assert any("Indeks on kehtiv" in s.value for s in at.sidebar.success)
        example_labels = [b.label for b in at.button]
        assert "Kuidas kirjeldatakse protsessi Plan?" in example_labels

        at.chat_input[0].set_value("Mida tähendab XQ1.2?").run()
        assert not at.exception
        md = " ".join(m.value for m in at.markdown)
        assert "[1]" in md and "[42]" not in md
        assert "PDF lk 3" in md
        assert any("olematule allikale" in w.value for w in at.warning)

        # Kustutamine nõuab kinnitust
        btn = next(b for b in at.sidebar.button if b.label == "Kustuta dokument ja indeks")
        btn.click().run()
        assert any(b.label == "Jah, kustuta" for b in at.sidebar.button)
        assert storage.get_document(doc.doc_id) is not None
        next(b for b in at.sidebar.button if b.label == "Jah, kustuta").click().run()
        assert storage.get_document(doc.doc_id) is None
    finally:
        srv.shutdown()
