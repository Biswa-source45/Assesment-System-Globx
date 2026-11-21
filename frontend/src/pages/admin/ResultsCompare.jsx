import { useEffect, useMemo, useState } from "react"
import { ArrowDown, ArrowUp } from "lucide-react"
import { get } from "@/lib/api"
import { RISK } from "@/lib/labels"
import { OUTCOME_TONE, RESULT, TONE } from "@/lib/verdict"
import { Loading } from "@/components/Spinner"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const num = (v) => (v == null ? "-" : v)
const mean = (list) => { const v = list.filter((x) => x != null); return v.length ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 10) / 10 : null }

// Every student side by side, the same figures as the Excel file: click a heading to sort. People deleted from the exam (the bin) are not here.
export default function ResultsCompare({ testId }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState("")
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState({ key: "rank", dir: 1 })
  useEffect(() => { get(`/tests/${testId}/results`).then(setD).catch((e) => setError(e.message)) }, [testId])

  const cols = useMemo(() => d && [
    { key: "rank", label: "Rank", val: (r) => r.rank },
    { key: "name", label: "Name", val: (r) => r.name.toLowerCase() },
    { key: "score", label: "Score", val: (r) => r.score, avg: true, show: (r) => (r.score != null ? `${r.score} / ${r.max}` : "-") },
    { key: "percent", label: "%", val: (r) => r.percent, avg: true, show: (r) => (r.percent != null ? `${r.percent}%` : "-") },
    ...d.sections.map((s) => ({ key: `s:${s.id}`, label: s.title, val: (r) => r.section_scores?.[s.id], avg: true, show: (r) => num(r.section_scores?.[s.id]) })),
    { key: "minutes", label: "Minutes", val: (r) => r.minutes, avg: true, show: (r) => num(r.minutes) },
    { key: "result", label: "Result", val: (r) => r.result, show: (r) => (r.result ? <Badge variant="outline" className={TONE[RESULT[r.result][1]]}>{RESULT[r.result][0]}</Badge> : "-") },
    { key: "risk", label: "Risk", val: (r) => r.risk_score, show: (r) => RISK[r.risk_level] ?? "-" },
  ], [d])

  const rows = useMemo(() => {
    if (!d) return []
    const c = cols.find((x) => x.key === sort.key)
    const needle = search.trim().toLowerCase()
    const list = d.rows.filter((r) => !needle || `${r.name} ${r.username}`.toLowerCase().includes(needle))
    return list.sort((a, b) => {
      const x = c.val(a), y = c.val(b)
      if (x == null || x === "") return y == null || y === "" ? 0 : 1  // nobody without a value goes above somebody with one, whichever way it is sorted
      if (y == null || y === "") return -1
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir
    })
  }, [d, cols, sort, search])

  if (error) return <p className="text-destructive">{error}</p>
  if (!d) return <Loading />
  const click = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === "rank" || key === "name" ? 1 : -1 }))  // marks start with the highest
  return (
    <div className="grid gap-3" data-testid="compare">
      <div className="flex flex-wrap items-center gap-3">
        <Input className="w-64" placeholder="Search by name or username" aria-label="Search the comparison" value={search} onChange={(e) => setSearch(e.target.value)} />
        <p className="text-sm text-muted-foreground">Click a heading to sort. The last row is the average of the people who appeared.</p>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            {cols.map((c) => (
              <TableHead key={c.key} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                <button type="button" className="inline-flex items-center gap-1 font-medium" onClick={() => click(c.key)}>
                  {c.label}{sort.key === c.key && (sort.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                </button>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const done = r.attempt_id && r.outcome !== "in_progress"
            return (
              <TableRow key={r.assignment_id} data-testid="compare-row">
                {cols.map((c) => (
                  <TableCell key={c.key} className={c.key === "name" ? "font-medium" : ""}>
                    {c.key === "rank" ? (r.rank ?? "-")
                      : c.key === "name" ? <>{r.name}{!done && <Badge variant="outline" className={`ml-2 ${TONE[OUTCOME_TONE[r.outcome] ?? "none"]}`}>{r.outcome_label}</Badge>}</>
                      : done ? c.show(r) : "-"}
                  </TableCell>
                ))}
              </TableRow>
            )
          })}
          {!rows.length && <TableRow><TableCell colSpan={cols.length} className="text-muted-foreground">{search.trim() ? "Nobody matches." : "Nobody was assigned to this exam."}</TableCell></TableRow>}
          {rows.length > 0 && (
            <TableRow className="bg-muted/50 font-medium" data-testid="compare-average">
              {cols.map((c) => <TableCell key={c.key}>{c.key === "name" ? "Average" : c.avg ? num(mean(rows.filter((r) => r.attempt_id && r.outcome !== "in_progress").map((r) => c.val(r)))) : ""}</TableCell>)}
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
