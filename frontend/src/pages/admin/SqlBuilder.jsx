import { useState } from "react"
import { toast } from "sonner"
import { Copy, Play, Plus, Trash2 } from "lucide-react"
import { post } from "@/lib/api"
import { buildInserts, buildSchema, checkTables, COLUMN_TYPES } from "@/lib/sqlbuild"
import { DataTable } from "@/pages/candidate/CodeView"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

// SQL question authoring without writing SQL: tables and datasets are grids, the expected output is computed from the solution query.
// Form fields used: f.tables [{name, columns:[{name,type}]}], f.datasets [{visibility, weight, purpose, rows:[table][row][cell]}],
// f.reference_sql, f.ordered, f.preview [{ok, columns, rows} | {ok:false, error}].
export default function SqlBuilder({ f, set }) {
  const [busy, setBusy] = useState(false)
  const stale = () => set("preview", null)

  // ---- tables
  const setTables = (tables) => { set("tables", tables); stale() }
  const setDatasets = (datasets) => set("datasets", datasets)
  const mapDatasets = (fn) => setDatasets(f.datasets.map(fn))
  const patchTable = (ti, patch) => setTables(f.tables.map((t, i) => (i === ti ? { ...t, ...patch } : t)))
  const addTable = () => {
    setTables([...f.tables, { name: "", columns: [{ name: "", type: "TEXT" }] }])
    mapDatasets((d) => ({ ...d, rows: [...d.rows, []] }))
  }
  const removeTable = (ti) => {
    setTables(f.tables.filter((_, i) => i !== ti))
    mapDatasets((d) => ({ ...d, rows: d.rows.filter((_, i) => i !== ti) }))
  }
  const addColumn = (ti) => patchTable(ti, { columns: [...f.tables[ti].columns, { name: "", type: "TEXT" }] })
  const patchColumn = (ti, ci, patch) => patchTable(ti, { columns: f.tables[ti].columns.map((c, i) => (i === ci ? { ...c, ...patch } : c)) })
  const removeColumn = (ti, ci) => {
    patchTable(ti, { columns: f.tables[ti].columns.filter((_, i) => i !== ci) })
    mapDatasets((d) => ({ ...d, rows: d.rows.map((rs, i) => (i === ti ? rs.map((r) => r.filter((_, j) => j !== ci)) : rs)) }))
  }

  // ---- datasets and rows
  const patchDataset = (di, patch) => mapDatasets((d, i) => (i === di ? { ...d, ...patch } : d))
  const addDataset = () => setDatasets([...f.datasets, { visibility: f.datasets.length ? "hidden" : "open", weight: 1, purpose: "", rows: f.tables.map(() => []) }])
  const duplicateDataset = (di) => setDatasets([...f.datasets.slice(0, di + 1), { ...structuredClone(f.datasets[di]), visibility: "hidden" }, ...f.datasets.slice(di + 1)])
  const removeDataset = (di) => { setDatasets(f.datasets.filter((_, i) => i !== di)); stale() }
  const patchRows = (di, ti, fn) => patchDataset(di, { rows: f.datasets[di].rows.map((rs, i) => (i === ti ? fn(rs) : rs)) })
  const addRow = (di, ti) => patchRows(di, ti, (rs) => [...rs, f.tables[ti].columns.map(() => "")])
  const removeRow = (di, ti, ri) => patchRows(di, ti, (rs) => rs.filter((_, i) => i !== ri))
  const setCell = (di, ti, ri, ci, v) => patchRows(di, ti, (rs) => rs.map((r, i) => (i === ri ? f.tables[ti].columns.map((_, j) => (j === ci ? v : r[j] ?? "")) : r)))

  async function run() {
    const bad = checkTables(f.tables)
    if (bad) return toast.error(bad)
    setBusy(true)
    try {
      const out = await post("/questions/sql-preview", {
        ddl: buildSchema(f.tables), reference_sql: f.reference_sql, datasets: f.datasets.map((d) => buildInserts(f.tables, d.rows)),
      })
      set("preview", out.results)
      toast.success("Expected output updated")
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Tables</CardTitle>
          <CardDescription>The tables the candidate's query will read. Fill in their rows in each dataset below.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {f.tables.map((t, ti) => (
            <div key={ti} className="grid gap-2 rounded-lg border p-3" data-testid="sql-table-def">
              <div className="flex items-center gap-2">
                <Input aria-label={`Table ${ti + 1} name`} placeholder="Table name, for example customers" value={t.name} onChange={(e) => patchTable(ti, { name: e.target.value })} />
                <Button variant="ghost" size="icon" aria-label={`Remove table ${ti + 1}`} onClick={() => removeTable(ti)}><Trash2 /></Button>
              </div>
              {t.columns.map((c, ci) => (
                <div key={ci} className="flex items-center gap-2 pl-4">
                  <Input aria-label={`Table ${ti + 1} column ${ci + 1} name`} placeholder="Column name" value={c.name} onChange={(e) => patchColumn(ti, ci, { name: e.target.value })} />
                  <Select value={c.type} onValueChange={(v) => patchColumn(ti, ci, { type: v })}>
                    <SelectTrigger className="w-36" aria-label={`Table ${ti + 1} column ${ci + 1} type`}><SelectValue /></SelectTrigger>
                    <SelectContent>{COLUMN_TYPES.map((x) => <SelectItem key={x} value={x}>{x}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button variant="ghost" size="icon" aria-label={`Remove column ${ci + 1} of table ${ti + 1}`} disabled={t.columns.length <= 1} onClick={() => removeColumn(ti, ci)}><Trash2 /></Button>
                </div>
              ))}
              <div className="pl-4"><Button variant="outline" size="sm" onClick={() => addColumn(ti)}><Plus /> Add column</Button></div>
            </div>
          ))}
          <div><Button variant="outline" size="sm" onClick={addTable}><Plus /> Add table</Button></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Solution query</CardTitle>
          <CardDescription>The one place you write SQL. Its result on each dataset becomes the expected output the candidate has to match.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <Textarea aria-label="Solution query" className="min-h-24 font-mono text-xs" placeholder="SELECT ..." value={f.reference_sql}
            onChange={(e) => { set("reference_sql", e.target.value); stale() }} />
          <Label className="flex items-center gap-2 font-normal">
            <Checkbox checked={f.ordered} onCheckedChange={(v) => set("ordered", v === true)} /> Row order matters (the candidate's rows must come in the same order)
          </Label>
          <div><Button variant="outline" size="sm" disabled={busy || !f.reference_sql.trim() || !f.datasets.length} onClick={run}><Play /> {busy ? "Running..." : "Run solution query on all datasets"}</Button></div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Datasets</CardTitle>
          <CardDescription>Each dataset is one test: the rows in the tables, and the expected output. Sample datasets are shown to the candidate (use 1 or 2); hidden ones decide the marks. Weights are relative.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {f.datasets.map((d, di) => {
            const pv = f.preview?.[di]
            return (
              <div key={di} className="grid gap-3 rounded-lg border p-3" data-testid="sql-dataset">
                <div className="flex flex-wrap items-center gap-2">
                  <b className="text-sm">Dataset {di + 1}</b>
                  <Select value={d.visibility} onValueChange={(v) => patchDataset(di, { visibility: v })}>
                    <SelectTrigger className="w-40" aria-label={`Dataset ${di + 1} visibility`}><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="open">Sample (visible)</SelectItem><SelectItem value="hidden">Hidden</SelectItem></SelectContent>
                  </Select>
                  <Input className="w-24" type="number" step="0.5" min="0.5" aria-label={`Dataset ${di + 1} weight`} value={d.weight} onChange={(e) => patchDataset(di, { weight: e.target.value })} />
                  <Input className="min-w-48 flex-1" aria-label={`Dataset ${di + 1} note`} placeholder="Note (what it tests)" value={d.purpose} onChange={(e) => patchDataset(di, { purpose: e.target.value })} />
                  <Button variant="ghost" size="icon" aria-label={`Duplicate dataset ${di + 1}`} onClick={() => duplicateDataset(di)}><Copy /></Button>
                  <Button variant="ghost" size="icon" aria-label={`Remove dataset ${di + 1}`} onClick={() => removeDataset(di)}><Trash2 /></Button>
                </div>
                {f.tables.map((t, ti) => (
                  <div key={ti} className="grid gap-1">
                    <span className="text-xs font-medium">{t.name || `Table ${ti + 1}`}</span>
                    <div className="overflow-auto rounded-md border">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="bg-muted/50">
                            {t.columns.map((c, ci) => <th key={ci} className="px-2 py-1 text-left text-xs font-medium">{c.name || `column ${ci + 1}`}</th>)}
                            <th className="w-10" />
                          </tr>
                        </thead>
                        <tbody>
                          {(d.rows[ti] ?? []).map((row, ri) => (
                            <tr key={ri} className="border-t">
                              {t.columns.map((c, ci) => (
                                <td key={ci} className="p-1">
                                  <Input className="h-8 text-xs" aria-label={`Dataset ${di + 1} ${t.name} row ${ri + 1} ${c.name}`} value={row[ci] ?? ""} onChange={(e) => setCell(di, ti, ri, ci, e.target.value)} />
                                </td>
                              ))}
                              <td className="p-1"><Button variant="ghost" size="icon" className="size-8" aria-label={`Remove row ${ri + 1} of ${t.name} in dataset ${di + 1}`} onClick={() => removeRow(di, ti, ri)}><Trash2 /></Button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div><Button variant="outline" size="sm" onClick={() => addRow(di, ti)}><Plus /> Add row to {t.name || `table ${ti + 1}`}</Button></div>
                  </div>
                ))}
                <div className="grid gap-1">
                  <span className="text-xs font-medium">Expected output</span>
                  {pv?.ok && <DataTable data={pv} />}
                  {pv && !pv.ok && <Alert variant="destructive" className="p-2 text-xs">{pv.error}</Alert>}
                  {!pv && <p className="text-xs text-muted-foreground">Run the solution query to see the expected output.</p>}
                </div>
              </div>
            )
          })}
          <div><Button variant="outline" size="sm" disabled={!f.tables.length} onClick={addDataset}><Plus /> Add dataset</Button></div>
          {!f.tables.length && <p className="text-xs text-muted-foreground">Add a table first.</p>}
        </CardContent>
      </Card>
    </>
  )
}
