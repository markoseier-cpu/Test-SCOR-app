import * as mupdf from "mupdf";
import fs from "fs";
const doc = mupdf.Document.openDocument(fs.readFileSync(process.argv[2]), "application/pdf");
const out = [];
for (let i = 0; i < doc.countPages(); i++) {
  const t = doc.loadPage(i).toStructuredText().asText();
  out.push(t);
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
const lines = out.map((t, i) => {
  const L = t.split("\n").map(s => s.trim()).filter(Boolean);
  return `${i + 1}|${(L[0] || "").slice(0, 60)}|${(L.at(-1) || "").slice(0, 30)}`;
});
fs.writeFileSync(process.argv[4], lines.join("\n"));
