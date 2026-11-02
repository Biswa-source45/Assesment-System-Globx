// The SQL question editor lets an author define tables and rows in a grid; these helpers turn that into the
// CREATE TABLE and INSERT statements the judge runs. The author never writes them.
export const COLUMN_TYPES = ["INTEGER", "REAL", "TEXT", "DATE"]

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

// Returns a message for the first problem in the table definitions, or "" when they are fine.
export function checkTables(tables) {
  if (!tables.length) return "Add at least one table."
  const seen = new Set()
  for (const t of tables) {
    if (!NAME.test(t.name)) return `Table name "${t.name}" is not valid. Use letters, digits and underscores, starting with a letter.`
    if (seen.has(t.name.toLowerCase())) return `Two tables are called "${t.name}".`
    seen.add(t.name.toLowerCase())
    if (!t.columns.length) return `Table "${t.name}" needs at least one column.`
    const cols = new Set()
    for (const c of t.columns) {
      if (!NAME.test(c.name)) return `Column name "${c.name}" in table "${t.name}" is not valid. Use letters, digits and underscores.`
      if (cols.has(c.name.toLowerCase())) return `Table "${t.name}" has two columns called "${c.name}".`
      cols.add(c.name.toLowerCase())
    }
  }
  return ""
}

export const buildSchema = (tables) =>
  tables.map((t) => `CREATE TABLE ${t.name} (${t.columns.map((c) => `${c.name} ${c.type}`).join(", ")});`).join("\n")

// An empty cell is NULL; numbers stay numbers in number columns; everything else is quoted text.
function literal(value, type) {
  const s = String(value ?? "").trim()
  if (s === "") return "NULL"
  if ((type === "INTEGER" || type === "REAL") && !Number.isNaN(Number(s))) return s
  return `'${s.replace(/'/g, "''")}'`
}

// rows[tableIndex] = [[cell, ...], ...]; rows with every cell empty are skipped.
export const buildInserts = (tables, rows) =>
  tables
    .flatMap((t, ti) =>
      (rows[ti] ?? [])
        .filter((r) => r.some((cell) => String(cell ?? "").trim() !== ""))
        .map((r) => `INSERT INTO ${t.name} VALUES (${t.columns.map((c, ci) => literal(r[ci], c.type)).join(", ")});`)
    )
    .join("\n")
