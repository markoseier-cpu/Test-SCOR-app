import React, { useEffect, useMemo, useState } from "react";
import { ATTRIBUTES, CATEGORIES, PDF_SECTIONS, PRACTICE_TYPES, TYPES, subtitle } from "./scor.js";

function useRoute() {
  const read = () => {
    const [path, query = ""] = window.location.hash.replace(/^#/, "").split("?");
    return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => { setRoute(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function useApi(url) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ data: null, error: null });
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "Not found" : `Request failed (${r.status})`))))
      .then((data) => live && setState({ data, error: null }))
      .catch((error) => live && setState({ data: null, error }));
    return () => { live = false; };
  }, [url]);
  return state;
}

const href = (code) => `#/e/${encodeURIComponent(code)}`;

function Code({ code }) {
  return <span className="code">{code}</span>;
}

function ElementRow({ e }) {
  return (
    <a className="row" href={href(e.code)}>
      <Code code={e.code} />
      <span className="row-name">{e.name}</span>
      <span className="row-meta">{subtitle(e)}</span>
    </a>
  );
}

function Loading({ state, children }) {
  if (state.error) return <p className="muted">Could not load data: {state.error.message}</p>;
  if (!state.data) return <p className="muted">Loading…</p>;
  return children(state.data);
}

function Home() {
  const stats = useApi("/api/stats");
  const l1 = useApi("/api/elements?type=metric&level=1");
  const l2proc = useApi("/api/elements?type=process&level=2");
  return (
    <>
      <section className="hero">
        <h1>SCOR 11.0 Explorer</h1>
        <p>
          Browse the Supply Chain Operations Reference model by code: performance metrics, processes,
          practices and people skills, and how they connect.
        </p>
        <Loading state={stats}>
          {(s) => (
            <div className="stats">
              {Object.entries(TYPES).map(([t, { label }]) => (
                <a key={t} className="stat" href={`#/browse/${t}`}>
                  <strong>{s.types[t] ?? 0}</strong>
                  <span>{label}</span>
                </a>
              ))}
            </div>
          )}
        </Loading>
      </section>

      <section>
        <h2>Performance attributes and level-1 metrics</h2>
        <Loading state={l1}>
          {(rows) => (
            <div className="grid">
              {ATTRIBUTES.map((a) => (
                <div key={a.code} className="card">
                  <div className="card-head">
                    <a href={`#/browse/metric?attribute=${encodeURIComponent(a.name)}`}><h3>{a.name}</h3></a>
                    <span className="pill">{a.focus}</span>
                  </div>
                  {rows.filter((e) => e.attribute === a.name).map((e) => (
                    <a key={e.code} className="mini" href={href(e.code)}><Code code={e.code} /> {e.name}</a>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Loading>
      </section>

      <section>
        <h2>Management processes</h2>
        <Loading state={l2proc}>
          {(rows) => (
            <div className="grid">
              {CATEGORIES.map((c) => (
                <div key={c.code} className="card">
                  <div className="card-head">
                    <a href={href(c.code)}><h3><Code code={c.code} /> {c.name}</h3></a>
                  </div>
                  {rows.filter((e) => e.category === c.name).map((e) => (
                    <a key={e.code} className="mini" href={href(e.code)}><Code code={e.code} /> {e.name}</a>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Loading>
      </section>
    </>
  );
}

function Filters({ type, params }) {
  const set = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    window.location.hash = `#/browse/${type}${next.toString() ? "?" + next : ""}`;
  };
  const select = (key, options, label) => (
    <label>
      {label}
      <select value={params.get(key) ?? ""} onChange={(ev) => set(key, ev.target.value)}>
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
  return (
    <div className="filters">
      {type === "metric" && select("attribute", ATTRIBUTES.map((a) => a.name), "Attribute")}
      {type === "metric" && select("level", ["1", "2", "3"], "Level")}
      {type === "process" && select("category", CATEGORIES.map((c) => c.name), "Process")}
      {type === "process" && select("level", ["1", "2", "3"], "Level")}
      {type === "practice" && select("practiceType", PRACTICE_TYPES, "Type")}
    </div>
  );
}

function Browse({ type, params }) {
  const [filter, setFilter] = useState("");
  const query = new URLSearchParams(params);
  query.set("type", type);
  const state = useApi(`/api/elements?${query}`);
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (state.data ?? []).filter((e) => !f || e.code.toLowerCase().includes(f) || e.name.toLowerCase().includes(f));
  }, [state.data, filter]);
  if (!TYPES[type]) return <p>Unknown section.</p>;
  return (
    <section>
      <h1>{TYPES[type].label}</h1>
      <div className="toolbar">
        <Filters type={type} params={params} />
        <input className="filter" placeholder="Filter this list…" value={filter} onChange={(ev) => setFilter(ev.target.value)} />
      </div>
      <Loading state={state}>
        {() => (
          <>
            <p className="muted">{shown.length} shown</p>
            <div className="list">{shown.map((e) => <ElementRow key={e.code} e={e} />)}</div>
          </>
        )}
      </Loading>
    </section>
  );
}

function Search({ q }) {
  const state = useApi(`/api/elements?q=${encodeURIComponent(q)}&limit=300`);
  return (
    <section>
      <h1>Search: “{q}”</h1>
      <Loading state={state}>
        {(rows) => rows.length === 0
          ? <p className="muted">No codes or titles match.</p>
          : (
            <>
              {Object.keys(TYPES).filter((t) => rows.some((e) => e.type === t)).map((t) => (
                <div key={t} className="group">
                  <h2>{TYPES[t].label}</h2>
                  <div className="list">{rows.filter((e) => e.type === t).map((e) => <ElementRow key={e.code} e={e} />)}</div>
                </div>
              ))}
            </>
          )}
      </Loading>
    </section>
  );
}

function Detail({ code }) {
  const state = useApi(`/api/elements/${encodeURIComponent(code)}`);
  return (
    <Loading state={state}>
      {({ element: e, ancestors, children, related }) => (
        <section>
          <nav className="crumbs">
            <a href={`#/browse/${e.type}`}>{TYPES[e.type]?.label}</a>
            {ancestors.map((a) => (
              <span key={a.code}> › <a href={href(a.code)}>{a.code}</a></span>
            ))}
          </nav>
          <div className="detail-head">
            <Code code={e.code} />
            <h1>{e.name}</h1>
            <p className="muted">{subtitle(e)}</p>
            {e.pdfPage && (
              <p className="source">
                Source: SCOR 11.0 PDF page {e.pdfPage}
                {PDF_SECTIONS[e.pdfSection] && <> ({e.pdfSection} {PDF_SECTIONS[e.pdfSection]})</>}
              </p>
            )}
          </div>

          {children.length > 0 && (
            <div className="group">
              <h2>{e.type === "metric" ? "Diagnostic metrics (next level)" : "Sub-processes"}</h2>
              <div className="list">{children.map((c) => <ElementRow key={c.code} e={c} />)}</div>
            </div>
          )}

          {Object.keys(TYPES).filter((t) => related.some((r) => r.type === t)).map((t) => (
            <div key={t} className="group">
              <h2>Related {TYPES[t].label.toLowerCase()} <span className="count">{related.filter((r) => r.type === t).length}</span></h2>
              <div className="list">{related.filter((r) => r.type === t).map((r) => <ElementRow key={r.code} e={r} />)}</div>
            </div>
          ))}

          {children.length === 0 && related.length === 0 && <p className="muted">No linked elements.</p>}
        </section>
      )}
    </Loading>
  );
}

export default function App() {
  const { parts, params } = useRoute();
  const [q, setQ] = useState("");
  const submit = (ev) => {
    ev.preventDefault();
    if (q.trim()) window.location.hash = `#/search?q=${encodeURIComponent(q.trim())}`;
  };
  let page;
  if (parts[0] === "browse") page = <Browse type={parts[1]} params={params} />;
  else if (parts[0] === "e") page = <Detail code={parts[1]} />;
  else if (parts[0] === "search") page = <Search q={params.get("q") ?? ""} />;
  else page = <Home />;
  return (
    <>
      <header className="top">
        <a className="brand" href="#/">SCOR Explorer</a>
        <nav className="tabs">
          {["metric", "process", "practice", "skill"].map((t) => (
            <a key={t} href={`#/browse/${t}`} className={parts[0] === "browse" && parts[1] === t ? "active" : ""}>{TYPES[t].label}</a>
          ))}
        </nav>
        <form className="search" onSubmit={submit}>
          <input placeholder="Search code or title, e.g. RL.1.1 or forecasting" value={q} onChange={(ev) => setQ(ev.target.value)} />
        </form>
      </header>
      <main>{page}</main>
      <footer className="foot">
        Student exercise. Codes, titles and relationships from SCOR 11.0 © Supply Chain Council, 2012. Definitions are not reproduced.
      </footer>
    </>
  );
}
