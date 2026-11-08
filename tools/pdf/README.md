# PDF extraction tools

One-off scripts that turned the SCOR 11.0 PDF into `data/scor.json`. They are not part of the deployed app,
and the PDF itself is not kept in the repository.

```bash
cd tools/pdf && npm install
node fix-fonts.mjs SCOR11PDF.pdf SCOR11-fixed.pdf   # rebuild missing text mappings (needs Windows Arial fonts)
node split.mjs SCOR11-fixed.pdf ./split              # one PDF per SCOR section
node extract-pages.mjs SCOR11-fixed.pdf pages.json pages.txt
node parse.mjs pages.json ../../data/scor.json       # codes, titles and relationships only
```

Some Responsiveness and Cost pages use an embedded Arial subset with an empty ToUnicode map, so their text
extracts as garbage. `fix-fonts.mjs` matches each glyph outline to the system Arial fonts and writes a
correct ToUnicode map into the PDF.
