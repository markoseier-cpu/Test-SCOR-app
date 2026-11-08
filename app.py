"""SCOR 11 dokumendiassistent – Streamlit kasutajaliides.

Käivitus:  streamlit run app.py   (kuulab ainult 127.0.0.1, vt .streamlit/config.toml)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

from scor_assistant.config import ConfigError, load_settings
from scor_assistant.indexing import IndexManager
from scor_assistant.ollama_client import (
    RECOMMENDED_EMBED,
    RECOMMENDED_LLMS,
    OllamaClient,
    OllamaError,
    looks_like_embedding_model,
)
from scor_assistant.pdf_processing import (
    PdfError,
    extract_pages,
    render_page_png,
    sha256_bytes,
    validate_upload,
)
from scor_assistant.pipeline import QueryConfig, ask, load_searcher
from scor_assistant.storage import Storage

EXAMPLE_QUESTIONS = [
    "Millised põhiprotsessid on selles dokumendis kirjeldatud?",
    "Kuidas kirjeldatakse protsessi Plan?",
    "Milliseid mõõdikuid dokument käsitleb?",
    "Leia mõiste order fulfillment cycle time definitsioon.",
]

st.set_page_config(page_title="SCOR 11 dokumendiassistent", page_icon="📄", layout="wide")


# ----------------------------------------------------------------------------- ressursid
def get_settings():
    # Ei kasuta vahemälu: .env muudatused rakenduvad lehe värskendamisel.
    return load_settings()


@st.cache_resource
def get_storage(db_path: str, vectors_dir: str, documents_dir: str) -> Storage:
    return Storage(Path(db_path), Path(vectors_dir), Path(documents_dir))


@st.cache_resource
def get_client(url: str, timeout: int, allow_remote: bool) -> OllamaClient:
    return OllamaClient(url, timeout, allow_remote)


@st.cache_resource(max_entries=4)
def get_searcher(_storage: Storage, doc_id: str, index_key: str):
    # index_key (seadete räsi + uuendusaeg) muudab vahemälu kehtetuks pärast uut indekseerimist
    return load_searcher(_storage, doc_id)


@st.cache_data(max_entries=32, show_spinner=False)
def page_image(pdf_path: str, page_no: int, highlight: str | None) -> bytes:
    return render_page_png(pdf_path, page_no, dpi=110, highlight=highlight)


try:
    settings = get_settings()
except ConfigError as exc:
    st.error(f"Seadistuse viga: {exc}")
    st.stop()

storage = get_storage(str(settings.db_path), str(settings.vectors_dir), str(settings.documents_dir))
client = get_client(settings.ollama_url, settings.request_timeout, settings.allow_remote_ollama)

ss = st.session_state
ss.setdefault("messages", [])          # [{"doc_id", "question", "result"}]
ss.setdefault("confirm_delete", False)
ss.setdefault("last_upload_key", None)
ss.setdefault("upload_report", None)
ss.setdefault("pending_question", None)
ss.setdefault("open_pages", set())


# ----------------------------------------------------------------------------- abifunktsioonid
def fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def ollama_models() -> tuple[list[str], str | None]:
    try:
        return client.list_models(), None
    except OllamaError as exc:
        return [], str(exc)


def choose_model(label: str, options: list[str], saved: str | None, default: str, key: str,
                 help_text: str) -> str:
    if not options:
        return st.text_input(label, value=saved or default, key=key + "_txt", help=help_text).strip()
    preferred = [o for o in (saved, default) if o]
    idx = 0
    for p in preferred:
        for i, o in enumerate(options):
            if o == p or o == f"{p}:latest":
                idx = i
                break
        else:
            continue
        break
    return st.selectbox(label, options, index=idx, key=key, help=help_text)


def open_in_system_viewer(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]  # avab kohaliku PDF-vaaturi
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')


# ----------------------------------------------------------------------------- külgpaneel
with st.sidebar:
    st.header("Dokument")

    uploaded = st.file_uploader(
        f"Laadi üles SCOR 11 PDF (kuni {settings.max_upload_mb} MB)", type=["pdf"],
        help="Fail salvestatakse ainult selle arvuti andmekausta. Sisu ei saadeta välistele teenustele.",
    )
    if uploaded is not None:
        upload_key = (uploaded.name, uploaded.size)
        if ss.last_upload_key != upload_key:
            ss.last_upload_key = upload_key
            data = uploaded.getvalue()
            try:
                validate_upload(uploaded.name, data, settings.max_upload_mb)
                digest = sha256_bytes(data)
                existing = storage.get_document(digest)
                if existing:
                    storage.set_app_state("active_doc", digest)
                    ss.upload_report = ("info", f"See fail (SHA-256 {digest[:12]}…) on juba lisatud. "
                                                "Kasutan olemasolevat dokumenti.", existing.extraction.get("warnings", []))
                else:
                    bar = st.progress(0.0, text="Eraldan PDF-ist teksti…")
                    result = extract_pages(
                        data, settings.extract_tables,
                        progress=lambda i, n: bar.progress(i / n, text=f"Eraldan teksti: lk {i}/{n}"),
                    )
                    bar.empty()
                    doc = storage.save_document(uploaded.name, digest, data, result, settings.extract_tables)
                    storage.set_app_state("active_doc", doc.doc_id)
                    ss.upload_report = (
                        "success",
                        f"Tekst eraldatud: {result.page_count} lehekülge, neist tekstiga "
                        f"{result.text_pages}; kokku {result.total_chars:,} märki. "
                        "Järgmine samm: „Indekseeri dokument”.".replace(",", " "),
                        result.warnings,
                    )
            except PdfError as exc:
                ss.upload_report = ("error", str(exc), [])
    if ss.upload_report:
        kind, msg, warns = ss.upload_report
        getattr(st, kind)(msg)
        for w in warns:
            st.warning(w)

    docs = storage.list_documents()
    active_id = storage.get_app_state("active_doc")
    if docs and active_id not in {d.doc_id for d in docs}:
        active_id = docs[0].doc_id
        storage.set_app_state("active_doc", active_id)
    active = None
    if docs:
        labels = {d.doc_id: f"{d.filename} ({d.page_count} lk)" for d in docs}
        ids = [d.doc_id for d in docs]
        sel = st.selectbox("Aktiivne dokument", ids, index=ids.index(active_id),
                           format_func=lambda i: labels[i])
        if sel != active_id:
            storage.set_app_state("active_doc", sel)
            active_id = sel
        active = storage.get_document(active_id)
    else:
        st.info("Dokumenti pole veel lisatud.")

    st.divider()
    st.header("Kohalikud mudelid")
    models, ollama_err = ollama_models()
    if ollama_err:
        st.error(ollama_err)
        st.caption("Ilma Ollamata saab PDF-i lisada ja teksti eraldada, kuid mitte indekseerida ega vastata.")
    elif not models:
        st.warning(
            "Ollamas pole ühtegi mudelit. Paigalda näiteks:\n\n"
            f"`ollama pull {RECOMMENDED_LLMS[0]}`\n\n`ollama pull {RECOMMENDED_EMBED}`"
        )
    llm_opts = sorted(models, key=lambda m: (looks_like_embedding_model(m), m))
    emb_opts = sorted(models, key=lambda m: (not looks_like_embedding_model(m), m))
    llm_model = choose_model(
        "Keelemudel (vastuste koostamine)", llm_opts, storage.get_app_state("llm_model"),
        settings.llm_model or RECOMMENDED_LLMS[0], "llm_select",
        "Suurem mudel annab üldjuhul parema vastuse, kuid on aeglasem ja vajab rohkem mälu.",
    )
    embed_model = choose_model(
        "Embedding-mudel (otsing)", emb_opts, storage.get_app_state("embed_model"),
        settings.embed_model or RECOMMENDED_EMBED, "emb_select",
        "Kasuta mitmekeelset mudelit (nt bge-m3), et eesti- ja ingliskeelsed küsimused leiaksid "
        "ingliskeelse teksti. Mudeli muutmisel tuleb dokument uuesti indekseerida.",
    )
    if llm_model:
        storage.set_app_state("llm_model", llm_model)
    if embed_model:
        storage.set_app_state("embed_model", embed_model)
    if models and llm_model and looks_like_embedding_model(llm_model):
        st.warning("Valitud keelemudel paistab olevat embedding-mudel ega oska vastuseid koostada.")

    manager = IndexManager(storage, client, embed_model, settings.chunk_tokens, settings.chunk_overlap,
                           settings.extract_tables, settings.embed_batch_size)

    st.divider()
    st.header("Indeks")
    status = manager.status(active) if active else None
    if active and status:
        st.caption(f"Fail: **{active.filename}** · {fmt_mb(active.size_bytes)} · SHA-256 `{active.sha256[:16]}…`")
        if status.ready:
            st.success(f"Indeks on kehtiv: {status.chunk_count} lõiku, embedding-mudel „{status.embed_model}”.")
        elif status.state == "stale":
            st.warning("Indeks on aegunud.\n\n" + "\n\n".join(status.reasons))
        elif status.state == "broken":
            st.error("\n\n".join(status.reasons))
        else:
            st.info("Dokument on indekseerimata.")
        for w in active.extraction.get("warnings", []):
            st.caption("⚠️ " + w)

        can_index = bool(embed_model) and not ollama_err and status.state != "broken"
        if st.button("Indekseeri dokument", type="primary", disabled=not can_index, width="stretch"):
            bar = st.progress(0.0, text="Alustan indekseerimist…")
            try:
                client.ensure_model(embed_model)
                status = manager.build(active, progress=lambda m, f: bar.progress(f, text=m))
                bar.empty()
                st.success(f"Indekseeritud: {status.chunk_count} lõiku.")
                st.rerun()
            except (OllamaError, PdfError, ValueError) as exc:
                bar.empty()
                st.error(f"Indekseerimine ebaõnnestus: {exc}")

        with open(active.pdf_path, "rb") as fh:
            st.download_button("Ava / laadi alla PDF", fh, file_name=active.filename, mime="application/pdf",
                               width="stretch")
        if st.button("Ava PDF arvuti PDF-vaaturis", width="stretch"):
            open_in_system_viewer(active.pdf_path)

        st.divider()
        if not ss.confirm_delete:
            if st.button("Kustuta dokument ja indeks", width="stretch"):
                ss.confirm_delete = True
                st.rerun()
        else:
            st.warning(f"Kas kustutada „{active.filename}”, selle tekst, indeks ja PDF-i koopia andmekaustast? "
                       "Seda ei saa tagasi võtta.")
            c1, c2 = st.columns(2)
            if c1.button("Jah, kustuta", type="primary"):
                storage.delete_document(active.doc_id)
                ss.messages = [m for m in ss.messages if m["doc_id"] != active.doc_id]
                ss.confirm_delete = False
                ss.upload_report = ("info", "Dokument ja indeks kustutati.", [])
                ss.last_upload_key = None
                st.rerun()
            if c2.button("Tühista"):
                ss.confirm_delete = False
                st.rerun()

    st.divider()
    if st.button("Tühjenda vestlus", width="stretch"):
        ss.messages = []
        ss.open_pages = set()
        st.rerun()
    st.caption(f"Andmekaust: `{settings.data_dir}` · Ollama: `{settings.ollama_url}`")


# ----------------------------------------------------------------------------- põhivaade
st.title("SCOR 11 dokumendiassistent")
st.caption("Vastused põhinevad ainult üles laaditud PDF-il. Kõik töötlemine toimub selles arvutis. "
           "Viited on kujul „PDF lk X” – see on PDF-faili lehekülg, mis võib erineda dokumendile trükitud numbrist.")


def render_source(src, msg_idx: int, doc) -> None:
    c = src.chunk
    sec = f" · jaotis: {c.section}" if c.section else ""
    st.markdown(f"**[{src.ref}] {c.filename} · PDF lk {c.page_no}**{sec}")
    st.text(c.text)  # originaalkatkend muutmata kujul
    has_table = "[Tabel]" in c.text
    if has_table:
        st.caption("⚠️ Katkend sisaldab tabelit – võrdle tabeli eraldust PDF-i leheküljega.")
    key = f"{msg_idx}-{src.ref}-{c.chunk_id}"
    if doc and Path(doc.pdf_path).is_file():
        if st.toggle(f"Näita PDF lk {c.page_no}", key="pg-" + key):
            try:
                st.image(page_image(doc.pdf_path, c.page_no, c.text), caption=f"{c.filename} · PDF lk {c.page_no}")
            except PdfError as exc:
                st.error(str(exc))


def render_hits_only(hits, msg_idx: int, doc) -> None:
    from scor_assistant.answering import Source

    for h in hits:
        render_source(Source(h.rank, h), msg_idx, doc)
        st.divider()


def render_result(res, msg_idx: int, doc) -> None:
    if res.error:
        st.error(f"Vastust ei saanud koostada: {res.error}")
        if res.hits:
            with st.expander(f"Otsingutulemused ({len(res.hits)}) – vastust ei koostatud", expanded=True):
                render_hits_only(res.hits, msg_idx, doc)
        return
    if res.not_found:
        st.info(res.answer)
    else:
        st.markdown(res.answer)
    for w in res.warnings:
        st.warning(w)
    if res.search_query != res.question:
        st.caption(f"Otsingupäring (täpsustatud vestluse põhjal): „{res.search_query}”")
    if res.cited:
        st.markdown("**Viited:**  \n" + "  \n".join(s.label() for s in res.cited))
    with st.expander(f"Allikad ({len(res.cited)} viidatud, {len(res.sources)} mudelile antud, "
                     f"{len(res.hits)} leitud)"):
        st.caption("Järjestus põhineb otsingul (semantiline + märksõna). See ei ole vastuse õigsuse hinnang.")
        cited_ids = {s.ref for s in res.cited}
        ordered = [s for s in res.sources if s.ref in cited_ids] + [s for s in res.sources if s.ref not in cited_ids]
        for s in ordered:
            render_source(s, msg_idx, doc)
            if s.ref not in cited_ids:
                st.caption("Seda allikat vastuses ei viidatud.")
            st.divider()


if not active:
    st.info("Alustamiseks laadi külgpaneelil üles SCOR 11 PDF, mille kasutamise õigus sul on, ja vajuta "
            "„Indekseeri dokument”.")

doc_messages = [m for m in ss.messages if active and m["doc_id"] == active.doc_id]
for i, m in enumerate(doc_messages):
    with st.chat_message("user"):
        st.markdown(m["question"])
    with st.chat_message("assistant"):
        render_result(m["result"], i, active)

ready = bool(active and status and status.ready and llm_model and not ollama_err)
if active and not ready:
    if ollama_err:
        st.warning("Küsimustele vastamiseks käivita Ollama (vt külgpaneeli teadet).")
    elif status and not status.ready:
        st.warning("Küsimuste esitamiseks indekseeri dokument (külgpaneel → „Indekseeri dokument”).")
    elif not llm_model:
        st.warning("Vali külgpaneelil keelemudel.")

if not doc_messages:
    st.markdown("**Näidisküsimused** (näited, mitte etteantud vastused):")
    cols = st.columns(2)
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if cols[i % 2].button(q, key=f"ex{i}", disabled=not ready, width="stretch"):
            ss.pending_question = q
            st.rerun()

typed = st.chat_input("Küsi dokumendi kohta (eesti või inglise keeles)…", disabled=not ready)
question = typed or ss.pending_question
ss.pending_question = None

if question and ready:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        state = storage.get_index_state(active.doc_id)
        history = [{"question": m["question"], "answer": m["result"].answer}
                   for m in doc_messages if not m["result"].error]
        cfg = QueryConfig(llm_model, embed_model, settings.top_k, settings.candidate_k, settings.num_ctx,
                          settings.answer_tokens, settings.temperature)
        placeholder = st.empty()
        with st.status("Töötlen küsimust…", expanded=True) as stat:
            try:
                searcher = get_searcher(storage, active.doc_id, f"{state.settings_hash}-{state.updated_at}")
            except Exception as exc:  # vigane indeks
                st.error(f"Indeksi laadimine ebaõnnestus: {exc}")
                st.stop()
            res = ask(question, searcher, client, client, cfg, history,
                      on_stage=lambda s: stat.write(s),
                      on_token=lambda t: placeholder.markdown(t + " ▌"))
            stat.update(label="Valmis" if not res.error else "Viga", state="complete" if not res.error else "error",
                        expanded=False)
        placeholder.empty()
        ss.messages.append({"doc_id": active.doc_id, "question": question, "result": res})
    # Renderda kogu vestlus ühtsest ajaloost, et allikapaneelide olek püsiks.
    st.rerun()
