import * as mupdf from "mupdf";
import fs from "fs";
import * as fontkit from "fontkit";
const [src, dst] = process.argv.slice(2);
const doc = mupdf.Document.openDocument(fs.readFileSync(src), "application/pdf").asPDF();
const refs = ["arial", "arialbd", "ariali", "arialbi"].map(n => fontkit.openSync(`C:/Windows/Fonts/${n}.ttf`));
const sig = (g) => g.path.commands.map(c => c.command[0] + c.args.map(Math.round).join(",")).join(" ");
const refMap = new Map();
for (const ref of refs) for (const cp of ref.characterSet) {
  if (cp > 0x2122 || cp < 0x20) continue;
  const s = sig(ref.glyphForCodePoint(cp));
  if (!refMap.has(s)) refMap.set(s, cp);
}
const done = new Set();
let fixed = 0, total = 0, missed = 0;
const hex = (n) => n.toString(16).toUpperCase().padStart(4, "0");
function fixFont(fref) {
  const f = fref.resolve();
  if (f.get("Subtype").toString() !== "/Type0") return;
  const key = fref.isIndirect() ? fref.asIndirect() : null;
  if (key !== null && done.has(key)) return;
  if (key !== null) done.add(key);
  const tu = f.get("ToUnicode");
  if (!tu.isNull() && /beginbf(char|range)/.test(tu.readStream().asString())) return;
  const ff = f.get("DescendantFonts").get(0).resolve().get("FontDescriptor").get("FontFile2");
  if (ff.isNull()) return;
  const buf = ff.readStream().asUint8Array();
  let sub;
  try { sub = fontkit.create(Buffer.from(buf)); } catch { return; }
  const pairs = [];
  for (let gid = 1; gid < sub.numGlyphs; gid++) {
    total++;
    const cp = refMap.get(sig(sub.getGlyph(gid)));
    if (cp) pairs.push(`<${hex(gid)}> <${hex(cp)}>`); else missed++;
  }
  let body = "";
  for (let i = 0; i < pairs.length; i += 100) {
    const chunk = pairs.slice(i, i + 100);
    body += `${chunk.length} beginbfchar\n${chunk.join("\n")}\nendbfchar\n`;
  }
  const cmap = `/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n${body}endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n`;
  f.put("ToUnicode", doc.addStream(cmap, {}));
  fixed++;
}
function walkRes(res, depth = 0) {
  if (res.isNull() || depth > 4) return;
  const fonts = res.get("Font");
  if (!fonts.isNull()) fonts.forEach((v) => fixFont(v));
  const xo = res.get("XObject");
  if (!xo.isNull()) xo.forEach((v) => { const r = v.resolve().get("Resources"); if (!r.isNull()) walkRes(r, depth + 1); });
}
for (let i = 0; i < doc.countPages(); i++) walkRes(doc.findPage(i).get("Resources"));
console.log("fonts fixed", fixed, "glyphs", total, "unmatched", missed);
fs.writeFileSync(dst, doc.saveToBuffer("garbage,compress").asUint8Array());
