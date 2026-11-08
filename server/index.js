import express from "express";
import path from "path";
import { fileURLToPath } from "url";
import { pool, migrateAndSeed } from "./db.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = express();

const ELEMENT_COLS = `code, name, type, level, parent, attribute, category, practice_type AS "practiceType",
  pdf_page AS "pdfPage", pdf_section AS "pdfSection"`;
// Codes sort like the PDF: by prefix, then numerically by each dotted part
const CODE_ORDER = `regexp_replace(code, '[0-9.]+$', ''),
  string_to_array(nullif(substring(code from '[0-9][0-9.]*$'), ''), '.')::int[] NULLS FIRST`;

const api = express.Router();
// Express 4 does not forward rejected promises to the error handler on its own
const wrap = (handler) => (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);

api.get("/stats", wrap(async (_req, res) => {
  const { rows } = await pool.query("SELECT type, count(*)::int AS count FROM scor_elements GROUP BY type");
  const links = await pool.query("SELECT count(*)::int AS count FROM scor_links");
  res.json({ types: Object.fromEntries(rows.map((r) => [r.type, r.count])), links: links.rows[0].count });
}));

api.get("/elements", wrap(async (req, res) => {
  const where = [], params = [];
  const add = (sql, v) => { params.push(v); where.push(sql.replaceAll("?", `$${params.length}`)); };
  for (const [key, col] of [["type", "type"], ["attribute", "attribute"], ["category", "category"], ["practiceType", "practice_type"]]) {
    if (req.query[key]) add(`${col} = ?`, String(req.query[key]));
  }
  if (req.query.level) add("level = ?", Number(req.query.level));
  if (req.query.q) add("(code ILIKE ? OR name ILIKE ?)", `%${String(req.query.q).trim()}%`);
  const limit = Math.min(Number(req.query.limit) || 2000, 2000);
  const { rows } = await pool.query(
    `SELECT ${ELEMENT_COLS} FROM scor_elements ${where.length ? "WHERE " + where.join(" AND ") : ""}
     ORDER BY ${CODE_ORDER} LIMIT ${limit}`,
    params
  );
  res.json(rows);
}));

api.get("/elements/:code", wrap(async (req, res) => {
  const { rows } = await pool.query(`SELECT ${ELEMENT_COLS} FROM scor_elements WHERE code = $1`, [req.params.code]);
  const element = rows[0];
  if (!element) return res.status(404).json({ error: "Not found" });

  const ancestors = await pool.query(
    `WITH RECURSIVE up AS (
       SELECT code, name, parent, 0 AS depth FROM scor_elements WHERE code = $1
       UNION ALL
       SELECT e.code, e.name, e.parent, up.depth + 1 FROM scor_elements e JOIN up ON e.code = up.parent
     ) SELECT code, name FROM up WHERE depth > 0 ORDER BY depth DESC`,
    [element.code]
  );
  const children = await pool.query(
    `SELECT ${ELEMENT_COLS} FROM scor_elements WHERE parent = $1 ORDER BY ${CODE_ORDER}`,
    [element.code]
  );
  const related = await pool.query(
    `SELECT ${ELEMENT_COLS} FROM scor_elements WHERE code IN (
       SELECT b FROM scor_links WHERE a = $1 UNION SELECT a FROM scor_links WHERE b = $1
     ) ORDER BY ${CODE_ORDER}`,
    [element.code]
  );
  res.json({ element, ancestors: ancestors.rows, children: children.rows, related: related.rows });
}));

api.use((_req, res) => res.status(404).json({ error: "Not found" }));

app.use("/api", api);
app.use(express.static(path.join(root, "dist")));
app.get("*", (_req, res) => res.sendFile(path.join(root, "dist", "index.html")));
app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: "Server error" });
});

const seeded = await migrateAndSeed(path.join(root, "data", "scor.json"));
console.log(seeded ? "Loaded SCOR data into the database" : "SCOR data already up to date");
const port = Number(process.env.PORT) || 3000;
// Listen on all interfaces so Railway's public proxy can reach the app
app.listen(port, "0.0.0.0", () =>console.log(`SCOR explorer listening on port ${port}`));
