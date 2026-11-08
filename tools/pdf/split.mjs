import * as mupdf from "mupdf";
import fs from "fs";
import path from "path";
const [src, outDir] = process.argv.slice(2);
const parts = [
  ["00", "Front-Matter", 1, 3], ["01", "Introduction", 4, 16],
  ["10", "Performance-Introduction", 17, 19], ["11", "Performance-Reliability", 20, 40],
  ["12", "Performance-Responsiveness", 41, 61], ["13", "Performance-Agility", 62, 99],
  ["14", "Performance-Cost", 100, 153], ["15", "Performance-Asset-Management", 154, 178],
  ["20", "Processes-Introduction", 179, 181], ["21", "Processes-Plan", 182, 226],
  ["22", "Processes-Source", 227, 266], ["23", "Processes-Make", 267, 303],
  ["24", "Processes-Deliver", 304, 374], ["25", "Processes-Return", 375, 415],
  ["26", "Processes-Enable", 416, 500],
  ["30", "Practices-Introduction", 501, 512], ["31", "Practices-Emerging", 513, 539],
  ["32", "Practices-Best", 540, 698], ["33", "Practices-Standard", 699, 730],
  ["40", "People-Skills", 731, 926], ["50", "Special-Applications-GreenSCOR", 927, 976],
];
const srcDoc = mupdf.Document.openDocument(fs.readFileSync(src), "application/pdf").asPDF();
fs.mkdirSync(outDir, { recursive: true });
for (const [n, name, a, b] of parts) {
  const out = new mupdf.PDFDocument();
  const g = out.newGraftMap();
  for (let p = a; p <= b; p++) g.graftPage(-1, srcDoc, p - 1);
  const file = path.join(outDir, `SCOR11-${n}-${name}_p${a}-${b}.pdf`);
  fs.writeFileSync(file, out.saveToBuffer("garbage,compress").asUint8Array());
  console.log(path.basename(file), b - a + 1, "pages");
}
