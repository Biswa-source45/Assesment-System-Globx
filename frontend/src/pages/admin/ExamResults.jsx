import { useCallback, useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"
import { Download } from "lucide-react"
import { api, get, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate, RESULT_STATE, RISK } from "@/lib/labels"
import { OUTCOME_TONE, RESULT, STATE_TONE, TONE } from "@/lib/verdict"
import { useConfirm } from "@/components/ConfirmDialog"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const POLL_MS = 5000

function banner(d) {
  const end = d.ends_at ? fmtDate(d.ends_at) : null
  if (d.state === "declared") return `Results were declared on ${fmtDate(d.declared_at)}. Candidates can see them.`
  if (d.state === "ready") return "Everything is marked. Look through the table, then declare the results."
  if (d.state === "needs_attention") return `${d.attention} answer(s) need your attention: the AI was unsure or could not mark them. Accept the suggested marks, or open the candidate and mark them. Results cannot be declared until then.`
  if (d.state === "calculating") return d.active ? `The end time has passed. Waiting for ${d.active} candidate(s) to be finished and marked, then the results are calculated automatically.` : "Calculating the results. This takes a moment."
  return end ? `The exam is still open. The results are calculated automatically after ${end}.` : "This exam has no end time. When everyone has finished, press Calculate results."
}

export default function ExamResults() {
  const { testId } = useParams()
  const { user } = useAuth()
  const confirm = useConfirm()
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => get(`/tests/${testId}/results`).then(setD).catch((e) => toast.error(e.message)), [testId])
  useEffect(() => { load() }, [load])
  const waiting = d && (d.state === "open" || d.state === "calculating" || d.active > 0)
  useEffect(() => {
    if (!waiting) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [waiting, load])

  async function run(fn, done) {
    setBusy(true)
    try { const out = await fn(); if (done) toast.success(done(out)); await load() } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const calculate = () => run(() => post(`/tests/${testId}/calculate`), () => "Calculating the results")
  async function acceptAll() {
    if (!(await confirm({ title: "Accept all suggested marks?", description: `The ${d.attention} answer(s) waiting for you take the mark the AI suggested (or the keyword mark when there was no AI mark). Answers with no suggestion stay for you to mark by hand.`, action: "Accept" }))) return
    run(() => post(`/tests/${testId}/accept-ai`), (o) => `${o.accepted} answer(s) accepted`)
  }
  async function declare(declared) {
    const yes = await confirm(declared
      ? { title: "Declare the results?", description: "Candidates can see their score and whether they passed. You can still change a mark later, and the candidate will then see the new score.", action: "Declare" }
      : { title: "Withdraw the results?", description: "Candidates will no longer see their result.", action: "Withdraw", destructive: true })
    if (yes) run(() => post(`/tests/${testId}/declare`, { declared }), () => (declared ? "Results declared" : "Results withdrawn"))
  }
  async function download(format) {
    try {
      const blob = await (await api(`/tests/${testId}/export?format=${format}`, { raw: true })).blob()
      const a = document.createElement("a")
      a.href = URL.createObjectURL(blob)
      a.download = `${d.title.replace(/[^A-Za-z0-9]+/g, "-")}-results.${format}`
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 1000)
    } catch (e) { toast.error(e.message) }
  }

  if (!d) return <p className="text-muted-foreground">Loading...</p>
  const evaluate = user.can.evaluate
  const s = d.summary
  const cards = [["Assigned", s.assigned], ["Appeared", s.appeared], ["Did not attend", s.absent], ["Ended early", s.ended_early], ["Passed", s.passed], ["Failed", s.failed], ["Did not attempt", s.not_attempted], ["Average", `${s.average_percent}%`]]

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="grid gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{d.title}</h1>
            <Badge variant="outline" className={TONE[STATE_TONE[d.state]]} data-testid="results-state">{RESULT_STATE[d.state]}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">Pass mark {d.cutoff} marks{d.ends_at ? `. Closes ${fmtDate(d.ends_at)}` : ""}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild><Link to="/admin/results">All results</Link></Button>
          {user.can.recruit && <Button variant="outline" onClick={() => download("csv")}><Download /> CSV</Button>}
          {user.can.recruit && <Button variant="outline" onClick={() => download("xlsx")}><Download /> Excel</Button>}
          {evaluate && <Button variant="outline" disabled={busy || d.active > 0} onClick={calculate}>{d.calculated_at ? "Calculate again" : "Calculate results"}</Button>}
          {evaluate && d.calculated_at && d.attention > 0 && <Button variant="outline" disabled={busy} onClick={acceptAll}>Accept all suggested marks</Button>}
          {evaluate && d.state !== "declared" && <Button disabled={busy || d.state !== "ready"} onClick={() => declare(true)}>Declare results</Button>}
          {evaluate && d.state === "declared" && <Button variant="outline" disabled={busy} onClick={() => declare(false)}>Withdraw results</Button>}
        </div>
      </div>

      <Alert className="p-3" data-testid="results-banner">{banner(d)}</Alert>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {cards.map(([label, value]) => (
          <Card key={label}><CardContent className="grid gap-0.5 pt-4"><span className="text-xs text-muted-foreground">{label}</span><span className="text-xl font-semibold" data-testid={`summary-${label}`}>{value}</span></CardContent></Card>
        ))}
      </div>

      <Table>
        <TableHeader>
          <TableRow><TableHead>Rank</TableHead><TableHead>Name</TableHead><TableHead>What happened</TableHead><TableHead>Score</TableHead><TableHead>%</TableHead><TableHead>Result</TableHead><TableHead>Needs attention</TableHead><TableHead>Risk</TableHead><TableHead /></TableRow>
        </TableHeader>
        <TableBody>
          {d.rows.map((r) => {
            const done = r.attempt_id && r.outcome !== "in_progress"
            return (
              <TableRow key={r.assignment_id} data-testid="results-row">
                <TableCell>{r.rank ?? "-"}</TableCell>
                <TableCell className="font-medium">{r.name}<div className="font-mono text-xs font-normal text-muted-foreground">{r.username}</div></TableCell>
                <TableCell><Badge variant="outline" className={TONE[OUTCOME_TONE[r.outcome] ?? "none"]}>{r.outcome_label}</Badge></TableCell>
                <TableCell>{done && r.score != null ? `${r.score} / ${r.max}` : "-"}</TableCell>
                <TableCell>{done && r.percent != null ? `${r.percent}%` : "-"}</TableCell>
                <TableCell>{done && r.result ? <Badge variant="outline" className={TONE[RESULT[r.result][1]]}>{RESULT[r.result][0]}</Badge> : "-"}</TableCell>
                <TableCell>{r.attention || "-"}</TableCell>
                <TableCell>{done ? (RISK[r.risk_level] ?? "-") : "-"}</TableCell>
                <TableCell className="text-right">{done && <Button asChild size="sm"><Link to={`/admin/results/${testId}/${r.attempt_id}`}>Review</Link></Button>}</TableCell>
              </TableRow>
            )
          })}
          {!d.rows.length && <TableRow><TableCell colSpan={9} className="text-muted-foreground">Nobody was assigned to this exam.</TableCell></TableRow>}
        </TableBody>
      </Table>
    </div>
  )
}
