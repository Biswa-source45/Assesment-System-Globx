import { useEffect, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { Download, FileText, Mail } from "lucide-react"
import { api, post } from "@/lib/api"
import { saveFile } from "@/lib/download"
import { useAuth } from "@/lib/auth"
import { fmtDate, RESULT_STATE, RISK } from "@/lib/labels"
import { OUTCOME_TONE, RESULT, STATE_TONE, TONE } from "@/lib/verdict"
import { useDebounced, usePaged } from "@/lib/usePaged"
import MoreRows from "@/components/MoreRows"
import { Loading } from "@/components/Spinner"
import { useConfirm } from "@/components/ConfirmDialog"
import PdfButton from "@/components/PdfButton"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import ExamAnalytics from "@/pages/admin/ExamAnalytics"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const POLL_MS = 5000
// What happened to a candidate's report-card mail.
const MAIL = { sent: ["Emailed", "good"], queued: ["Sending...", "info"], failed: ["Failed", "bad"], logged: ["Not sent", "part"], no_email: ["No e-mail", "none"] }

function mailLine(m) {
  const parts = [m.sent && `${m.sent} sent`, m.queued && `${m.queued} sending`, m.failed && `${m.failed} failed`, m.logged && `${m.logged} not sent`, m.no_email && `${m.no_email} without an e-mail address`].filter(Boolean)
  return parts.length ? `Report cards by e-mail: ${parts.join(", ")}.` : "Report cards by e-mail: none yet."
}

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
  const [busy, setBusy] = useState(false)
  const [search, setSearch] = useState("")
  const [params, setParams] = useSearchParams()
  // the summary always covers everyone; the table comes 50 people at a time, the next 50 when it is scrolled to its end (quiet: the 5-second refresh shows no spinner)
  const paged = usePaged(`/tests/${testId}/results`, { q: useDebounced(search.trim()) }, { idKey: "assignment_id", quiet: true })
  const d = paged.meta && paged.rows ? { ...paged.meta, rows: paged.rows } : null
  const load = paged.reload
  useEffect(() => { if (paged.error && !paged.rows) toast.error(paged.error) }, [paged.error, paged.rows])
  const waiting = d && (d.state === "open" || d.state === "calculating" || d.active > 0 || d.mail.queued > 0)
  useEffect(() => {
    if (!waiting) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [waiting, load])

  async function run(fn, done) {
    setBusy(true)
    try { const out = await fn(); if (done) toast.success(done(out)); await load() } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  async function calculate() {
    const yes = await confirm({ title: d.calculated_at ? "Calculate the results again?" : "Calculate the results?", description: "Every candidate is marked again from the saved answers. Marks you set by hand are kept.", action: "Calculate" })
    if (yes) run(() => post(`/tests/${testId}/calculate`), () => "Calculating the results")
  }
  async function acceptAll() {
    if (!(await confirm({ title: "Accept all suggested marks?", description: `The ${d.attention} answer(s) waiting for you take the mark the AI suggested (or the keyword mark when there was no AI mark). Answers with no suggestion stay for you to mark by hand.`, action: "Accept" }))) return
    run(() => post(`/tests/${testId}/accept-ai`), (o) => `${o.accepted} answer(s) accepted`)
  }
  async function declare(declared) {
    const yes = await confirm(declared
      ? { title: "Declare the results?", description: "Candidates can see their score, whether they passed and their report card. Each candidate with an e-mail address is sent the report card as a PDF. You can still change a mark later, and the candidate will then see the new score (a mail already sent is not recalled).", action: "Declare" }
      : { title: "Withdraw the results?", description: "Candidates will no longer see their result.", action: "Withdraw", destructive: true })
    if (yes) run(() => post(`/tests/${testId}/declare`, { declared }), (o) => (declared ? `Results declared${o.mails?.queued ? `. ${o.mails.queued} report card(s) are being e-mailed` : ""}` : "Results withdrawn"))
  }
  async function emailCards() {
    const yes = await confirm({ title: "E-mail the report cards?", description: "Every candidate with an e-mail address who has not received their report card is sent it now, and mails that failed are tried again. Nobody gets the same report card twice. A report card already sent keeps the marks it had when it was sent.", action: "Send" })
    if (yes) run(() => post(`/tests/${testId}/email-report-cards`), (o) => `${o.queued + o.requeued} report card(s) are being e-mailed`)
  }
  const fileOf = (path, name) => saveFile(path, name).catch((e) => toast.error(e.message))
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

  if (!d) return paged.error ? <p className="text-destructive">{paged.error}</p> : <Loading />
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
          {s.appeared > 0 && <Button variant="outline" onClick={() => fileOf(`/tests/${testId}/report-cards.zip`, "report-cards.zip")}><FileText /> Report cards (ZIP)</Button>}
          {evaluate && <Button variant="outline" disabled={busy || d.active > 0} onClick={calculate}>{d.calculated_at ? "Calculate again" : "Calculate results"}</Button>}
          {evaluate && d.calculated_at && d.attention > 0 && <Button variant="outline" disabled={busy} onClick={acceptAll}>Accept all suggested marks</Button>}
          {evaluate && d.state !== "declared" && <Button disabled={busy || d.state !== "ready"} onClick={() => declare(true)}>Declare results</Button>}
          {evaluate && d.state === "declared" && <Button variant="outline" disabled={busy || !d.mail.shared} onClick={emailCards}><Mail /> E-mail report cards</Button>}
          {evaluate && d.state === "declared" && <Button variant="outline" disabled={busy} onClick={() => declare(false)}>Withdraw results</Button>}
        </div>
      </div>

      <Tabs value={params.get("tab") ?? "results"} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="results">Results</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
        </TabsList>
        <TabsContent value="results" className="grid gap-4 pt-2">
          <Alert className="p-3" data-testid="results-banner">{banner(d)}</Alert>
          {d.state === "declared" && (
            <div className="grid gap-1 text-sm text-muted-foreground" data-testid="mail-summary">
              <p>{mailLine(d.mail)}</p>
              {!d.mail.shared && <p>This exam does not show results to candidates, so no report cards are sent.</p>}
              {d.mail.shared && !d.mail.smtp && <p>E-mail is not set up on this server, so nothing was sent. Candidates can still sign in and download their report card.</p>}
              {d.mail.failed > 0 && d.mail.error && <p className="text-destructive">The mail server said: {d.mail.error}</p>}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            {cards.map(([label, value]) => (
              <Card key={label}><CardContent className="grid gap-0.5 pt-4"><span className="text-xs text-muted-foreground">{label}</span><span className="text-xl font-semibold" data-testid={`summary-${label}`}>{value}</span></CardContent></Card>
            ))}
          </div>

          <Input className="w-64" placeholder="Search by name or username" aria-label="Search the results" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Table>
            <TableHeader>
              <TableRow><TableHead>Rank</TableHead><TableHead>Name</TableHead><TableHead>What happened</TableHead><TableHead>Score</TableHead><TableHead>%</TableHead><TableHead>Result</TableHead><TableHead>Needs attention</TableHead><TableHead>Risk</TableHead><TableHead>Report card</TableHead><TableHead /></TableRow>
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
                    <TableCell>
                      {done && (
                        <div className="flex items-center gap-2">
                          <PdfButton path={`/attempts/${r.attempt_id}/report-card.pdf`} size="sm" variant="outline" aria-label={`Report card of ${r.name}`} label="PDF" description={r.name} />
                          {d.state === "declared" && r.mail && <Badge variant="outline" className={TONE[MAIL[r.mail][1]]} data-testid="mail-status">{MAIL[r.mail][0]}</Badge>}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right">{done && <Button asChild size="sm"><Link to={`/admin/results/${testId}/${r.attempt_id}`}>Review</Link></Button>}</TableCell>
                  </TableRow>
                )
              })}
              {!d.rows.length && <TableRow><TableCell colSpan={10} className="text-muted-foreground">{search.trim() ? "Nobody matches." : "Nobody was assigned to this exam."}</TableCell></TableRow>}
            </TableBody>
          </Table>
          <MoreRows paged={paged} what="people" />
        </TabsContent>
        <TabsContent value="analytics" className="pt-2"><ExamAnalytics testId={testId} /></TabsContent>
      </Tabs>
    </div>
  )
}
