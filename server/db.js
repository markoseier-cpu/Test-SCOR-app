import fs from "fs";
import pg from "pg";

if (!process.env.DATABASE_URL) {
  throw new Error("DATABASE_URL is not set (it is provided by the Railway PostgreSQL service)");
}

export const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.PGSSL === "true" ? { rejectUnauthorized: false } : false,
});

const SCHEMA = `
CREATE TABLE IF NOT EXISTS scor_elements (
  code          TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  type          TEXT NOT NULL,
  level         INTEGER,
  parent        TEXT,
  attribute     TEXT,
  category      TEXT,
  practice_type TEXT,
  pdf_page      INTEGER,
  pdf_section   TEXT
);
CREATE INDEX IF NOT EXISTS scor_elements_type_idx ON scor_elements (type);
CREATE INDEX IF NOT EXISTS scor_elements_parent_idx ON scor_elements (parent);
CREATE TABLE IF NOT EXISTS scor_links (
  a TEXT NOT NULL REFERENCES scor_elements(code) ON DELETE CASCADE,
  b TEXT NOT NULL REFERENCES scor_elements(code) ON DELETE CASCADE,
  PRIMARY KEY (a, b)
);
CREATE INDEX IF NOT EXISTS scor_links_b_idx ON scor_links (b);
CREATE TABLE IF NOT EXISTS scor_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
`;

// Loads data/scor.json into the database whenever the file's version differs from the loaded one.
export async function migrateAndSeed(dataFile) {
  const raw = fs.readFileSync(dataFile, "utf8");
  const version = `${raw.length}:${hash(raw)}`;
  const client = await pool.connect();
  try {
    await client.query(SCHEMA);
    const { rows } = await client.query("SELECT value FROM scor_meta WHERE key = 'data_version'");
    if (rows[0]?.value === version) return false;

    const data = JSON.parse(raw);
    await client.query("BEGIN");
    await client.query("TRUNCATE scor_links, scor_elements");
    const cols = ["code", "name", "type", "level", "parent", "attribute", "category", "practice_type", "pdf_page", "pdf_section"];
    for (let i = 0; i < data.elements.length; i += 500) {
      const chunk = data.elements.slice(i, i + 500);
      const values = [];
      const tuples = chunk.map((e, r) => {
        values.push(e.code, e.name, e.type, e.level, e.parent, e.attribute ?? null, e.category ?? null, e.practiceType ?? null, e.page, e.pdfSection ?? null);
        return `(${cols.map((_, c) => `$${r * cols.length + c + 1}`).join(",")})`;
      });
      await client.query(`INSERT INTO scor_elements (${cols.join(",")}) VALUES ${tuples.join(",")}`, values);
    }
    for (let i = 0; i < data.links.length; i += 1000) {
      const chunk = data.links.slice(i, i + 1000);
      const tuples = chunk.map((_, r) => `($${r * 2 + 1},$${r * 2 + 2})`);
      await client.query(`INSERT INTO scor_links (a, b) VALUES ${tuples.join(",")} ON CONFLICT DO NOTHING`, chunk.flat());
    }
    await client.query(
      "INSERT INTO scor_meta (key, value) VALUES ('data_version', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
      [version]
    );
    await client.query("COMMIT");
    return true;
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(16);
}
