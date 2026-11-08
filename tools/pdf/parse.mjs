import fs from "fs";
const pages = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const CODE = /^(?:(?:RL|RS|AG|CO|AM|GS)\.\d+\.\d+|s(?:[PSMDE]|[SD]R|R)\d*(?:\.\d+)?|BP\.\d+|H[SEAT]\.\d{4})$/;
const L3CODE = /^(RL|RS|AG|CO|AM)\.3\.\d+$/;
const PROC_BULLET = /^(s(?:[PSMDE]|[SD]R|R)\d*(?:\.\d+)?)\s/;
const PAGENO = /^(?:i|\d+)(?:\.\d+)+$/;
const LINK = { Hierarchy: "hierarchy", Metrics: "metric", Processes: "process", Practices: "practice", People: "skill", Skills: "skill", Experiences: "experience", Aptitudes: "aptitude", Trainings: "training" };
const STOP = new Set(["Workflow", "Calculation", "Discussion", "Data collection", "Inputs", "Outputs"]);
const chapters = [
  [20, 178, "metric"], [182, 500, "process"], [513, 539, "practice", "Emerging"], [540, 698, "practice", "Best"],
  [699, 730, "practice", "Standard"], [731, 926, "skill"], [927, 976, "metric"],
];
const procChapter = [[182, 226, "Plan"], [227, 266, "Source"], [267, 303, "Make"], [304, 374, "Deliver"], [375, 415, "Return"], [416, 500, "Enable"]];
const typeOf = (c) => /^(RL|RS|AG|CO|AM|GS)\./.test(c) ? "metric" : c.startsWith("s") ? "process" : c.startsWith("BP") ? "practice"
  : { HS: "skill", HE: "experience", HA: "aptitude", HT: "training" }[c.slice(0, 2)];
// Cost codes appear both as CO.2.2 and CO.2.002; the PDF's own pages use three digits
const norm = (c) => c.replace(/^CO\.(\d)\.(\d+)$/, (_, l, n) => `CO.${l}.${n.padStart(3, "0")}`);
const section0 = (pageno) => pageno.split(".").slice(0, 2).join(".");

const elements = new Map(), names = new Map(), fallbackNames = new Map(), links = new Set();
let cur = null, section = null;
pages.forEach((text, i) => {
  const pg = i + 1;
  const ch = chapters.find(([a, b]) => pg >= a && pg <= b);
  if (!ch) return;
  const L = text.split("\n").map((s) => s.trim()).filter(Boolean);
  if (L.length < 3 || !PAGENO.test(L.at(-1))) return;

  // Level-3 metric tables: rows of code, title, definition and "• sXX Process" bullets
  if (/^(RL|RS|AG|CO|AM)$/.test(L.at(-2))) {
    if (L[0] === "Level-3 Metrics") cur = "L3TABLE";
    if (cur !== "L3TABLE") return;
    let m = null;
    for (let j = 0; j < L.length - 2; j++) {
      const l = L[j];
      if (L3CODE.test(l)) {
        m = norm(l);
        if (!fallbackNames.has(m)) fallbackNames.set(m, L[j + 1].replace(/\s+/g, " "));
        if (!elements.has(m)) elements.set(m, { code: m, name: null, type: "metric", page: pg, pdfSection: section0(L.at(-1)) });
        j++;
      } else if (m && PROC_BULLET.test(l)) {
        links.add(JSON.stringify([m, l.match(PROC_BULLET)[1], "process"]));
      }
    }
    return;
  }

  if (!CODE.test(L.at(-3))) { cur = null; return; }
  const code = norm(L.at(-3)), name = L.at(-2);
  if (cur !== code) { cur = code; section = null; }
  if (!elements.has(code)) {
    const e = { code, name, type: typeOf(code), page: pg, pdfSection: section0(L.at(-1)) };
    if (ch[3]) e.practiceType = ch[3];
    const pc = procChapter.find(([a, b]) => pg >= a && pg <= b);
    if (e.type === "process" && pc) e.category = pc[2];
    elements.set(code, e);
  }
  const body = L.slice(0, -3);
  for (let j = 0; j < body.length; j++) {
    const l = body[j];
    if (LINK[l]) { section = LINK[l]; continue; }
    if (STOP.has(l)) { section = null; continue; }
    if (section && CODE.test(l) && j + 1 < body.length && !CODE.test(body[j + 1])) {
      const c = norm(l);
      if (!names.has(c)) names.set(c, body[j + 1]);
      if (c !== code) links.add(JSON.stringify([code, c, section]));
      j++;
    }
  }
});

for (const e of elements.values()) if (!e.name) e.name = names.get(e.code) || fallbackNames.get(e.code);
// codes that only appear as references (experiences, trainings, some metrics) get their reference title
for (const [c, n] of names) if (!elements.has(c)) elements.set(c, { code: c, name: n, type: typeOf(c), page: null });
const levelOf = (e) => {
  if (e.type === "metric") return +e.code.split(".")[1];
  if (e.type === "process") return e.code.includes(".") ? 3 : /\d/.test(e.code) ? 2 : 1;
  return null;
};
for (const e of elements.values()) e.level = levelOf(e);

// Hierarchy entries become parent/child edges, everything else is a cross-reference
const parent = {}, xref = new Set();
for (const s of links) {
  const [a, b, kind] = JSON.parse(s);
  const ea = elements.get(a), eb = elements.get(b);
  if (!ea || !eb) continue;
  if (kind === "hierarchy") {
    if (ea.type === eb.type && ea.level && eb.level) {
      if (eb.level === ea.level + 1) parent[b] ??= a;
      else if (eb.level === ea.level - 1) parent[a] ??= b;
    }
    continue;
  }
  const [x, y] = [a, b].sort();
  xref.add(x + "|" + y);
}
// process parents follow from the code when the PDF gives no hierarchy entry
for (const e of elements.values()) {
  if (e.type !== "process" || parent[e.code]) continue;
  if (e.level === 3) parent[e.code] = e.code.split(".")[0];
  else if (e.level === 2) parent[e.code] = /^s[SD]R/.test(e.code) ? "sR" : e.code.replace(/\d+$/, "");
}
for (const e of elements.values()) {
  if (e.type === "process" && !e.category) e.category = { P: "Plan", S: "Source", M: "Make", D: "Deliver", R: "Return", E: "Enable" }[/^s[SD]R/.test(e.code) ? "R" : e.code[1]];
  if (e.type === "metric") e.attribute = { RL: "Reliability", RS: "Responsiveness", AG: "Agility", CO: "Cost", AM: "Asset Management Efficiency", GS: "GreenSCOR" }[e.code.slice(0, 2)];
  const p = parent[e.code];
  e.parent = p && elements.has(p) ? p : null;
}

const out = {
  source: "SCOR 11.0 (Supply Chain Council, 2012): codes, titles and relationships only",
  elements: [...elements.values()].sort((a, b) => a.code.localeCompare(b.code, "en", { numeric: true })),
  links: [...xref].sort().map((s) => s.split("|")),
};
fs.writeFileSync(process.argv[3], JSON.stringify(out));
const by = {};
for (const e of out.elements) by[e.type] = (by[e.type] || 0) + 1;
console.log(by, "links", out.links.length);
const orphans = out.elements.filter((e) => (e.type === "metric" || e.type === "process") && e.level > 1 && !e.parent);
console.log("no parent:", orphans.length, orphans.slice(0, 40).map((e) => e.code).join(" "));
