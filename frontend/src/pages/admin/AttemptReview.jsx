import { useCallback, useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"
import { get, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { ENDED, RISK, fmtDate } from "@/lib/labels"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import Snapshot from "@/components/Snapshot"
import { useConfirm } from "@/components/ConfirmDialog"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

const plain = (html) => new DOMParser().parseFromString(html || "", "text/html").body.textContent  // the candidate's text, never run as HTML
const time = (iso) => new Date(iso).toLocaleTimeString([], { timeStyle: "medium" })
const words = (type) => type.replace(/_/g, " ")

function MarkDialog({ q, onClose, onSaved }) {
  const [score, setScore] = useState(String(q.score ?? 0))
  const [reason, setReason] = useState("")
  const [feedback, setFeedback] = useState(q.feedback ?? "")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      await post(`/answers/${q.answer_id}/evaluate`, { final_score: Number(score), override_reason: reason, feedback })
      toast.success("Mark saved")
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Mark: {q.title}</DialogTitle>
            <DialogDescription>Out of {q.marks}{q.negative ? ` (down to -${q.negative})` : ""}. If your mark differs from the suggested {q.score}, say why. The reason is kept with the mark.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5"><Label htmlFor="m-score">Mark</Label><Input id="m-score" type="number" step="0.25" min={-q.negative} max={q.marks} required value={score} onChange={(e) => setScore(e.target.value)} className="w-32" /></div>
          <div className="grid gap-1.5"><Label htmlFor="m-reason">Reason for changing the mark</Label><Textarea id="m-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          <div className="grid gap-1.5"><Label htmlFor="m-feedback">Feedback for the candidate (optional)</Label><Textarea id="m-feedback" value={feedback} onChange={(e) => setFeedback(e.target.value)} /></div>
          {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy}>{busy ? "Saving..." : "Save mark"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Answer({ q }) {
  if (q.type.startsWith("mcq")) {
    return <p className="text-sm">Chose: <b>{q.selected.join(", ") || "nothing"}</b>. Correct: <b>{q.correct.join(", ")}</b></p>
  }
  if (q.type === "short" || q.type === "long") {
    return (
      <div className="grid gap-2 text-sm">
        <p className="whitespace-pre-wrap rounded-md bg-muted p-3" data-testid="answer-text">{plain(q.answer_html) || "No answer"}</p>
        {q.files?.length > 0 && <p className="text-xs text-muted-foreground">{q.files.length} file(s) attached</p>}
        {q.ai_rationale && <p className="text-xs text-muted-foreground">AI{q.ai_score != null ? ` suggested ${q.ai_score}` : ""}: {q.ai_rationale}</p>}
      </div>
    )
  }
  const sub = q.submission
  if (!sub?.id) return <p className="text-sm text-muted-foreground">No program was submitted or saved.</p>
  return (
    <div className="grid gap-2 text-sm">
      <p className="text-xs text-muted-foreground">{sub.language}, {sub.submissions} submission(s), passed {sub.score} of {sub.max} marks' worth of cases</p>
      <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">{sub.source}</pre>
      <div className="flex flex-wrap gap-1.5">
        {sub.cases.map((c) => <Badge key={c.ordinal} variant={c.verdict === "AC" ? "default" : "destructive"}>{c.visibility === "open" ? "Sample" : "Hidden"} {c.ordinal}: {c.verdict}</Badge>)}
      </div>
    </div>
  )
}

export default function AttemptReview() {
  const { testId, attemptId } = useParams()
  const { user } = useAuth()
  const confirm = useConfirm()
  const [rep, setRep] = useState(null)
  const [mark, setMark] = useState(null)
  const [onlyProblems, setOnlyProblems] = useState(true)
  const [shown, setShown] = useState(24)
  const load = useCallback(() => get(`/reports/attempts/${attemptId}`).then(setRep).catch((e) => toast.error(e.message)), [attemptId])
  useEffect(() => { load() }, [load])

  async function act(fn, done) {
    try { await fn(); toast.success(done); load() } catch (e) { toast.error(e.message) }
  }
  const accept = (q) => act(() => post(`/answers/${q.answer_id}/evaluate`, { final_score: q.score }), "Mark accepted")
  async function markAgain(q) {
    if (!(await confirm({ title: "Mark with AI again?", description: "The AI marks this answer again and its mark replaces the current one, including a mark you set by hand.", action: "Mark again", destructive: true }))) return
    act(() => post(`/answers/${q.answer_id}/ai`), "Marked again")
  }

  if (!rep) return <p className="text-muted-foreground">Loading...</p>
  const a = rep.attempt, p = rep.proctoring
  const problems = p.snapshots.filter((s) => s.kind === "webcam" && s.faces !== 1)
  const pics = (onlyProblems && problems.length ? problems : p.snapshots.filter((s) => s.kind === "webcam"))
  const evaluate = user.can.evaluate

  return (
    <div className="grid max-w-5xl gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold">{rep.candidate.name}</h1>
          <p className="text-sm text-muted-foreground">{rep.test.title}. {ENDED[a.submit_reason] ?? a.submit_reason}{a.submitted_at ? `, ${fmtDate(a.submitted_at)}` : ""}</p>
        </div>
        <Button variant="ghost" asChild><Link to={`/admin/results/${testId}`}>Back to the results</Link></Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[["Score", `${a.total_score} / ${a.max_score}`], ["Percent", `${a.percent}%`], ["Result", a.below_cutoff ? "Not passed" : "Passed"], ["Rank", a.rank ? `${a.rank} of ${a.of}` : "-"]].map(([label, value]) => (
          <Card key={label}><CardContent className="grid gap-0.5 pt-4"><span className="text-xs text-muted-foreground">{label}</span><span className="text-xl font-semibold" data-testid={`review-${label}`}>{value}</span></CardContent></Card>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>Sections</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Section</TableHead><TableHead>Score</TableHead><TableHead>Average of everyone</TableHead></TableRow></TableHeader>
            <TableBody>{rep.sections.map((s) => <TableRow key={s.id}><TableCell>{s.title}</TableCell><TableCell>{s.score} / {s.max}</TableCell><TableCell>{s.average}</TableCell></TableRow>)}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid gap-3">
        <h2 className="text-lg font-semibold">Answers ({a.attempted} of {a.questions} attempted)</h2>
        {rep.questions.map((q) => (
          <Card key={q.question_id} data-testid="review-question">
            <CardContent className="grid gap-3 pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="grow font-medium">{q.title}</span>
                <Badge variant="secondary">{TYPE_LABEL[q.type]}</Badge>
                {q.status === "review" && <Badge variant="destructive" data-testid="needs-attention">Needs attention</Badge>}
                {q.flags?.length > 0 && <Badge variant="outline">{q.flags.join(", ").replace(/_/g, " ")}</Badge>}
                <span className="w-24 text-right font-semibold" data-testid="question-score">{q.score ?? 0} / {q.marks}</span>
              </div>
              <Answer q={q} />
              {q.feedback && <p className="text-xs text-muted-foreground">Feedback: {q.feedback}</p>}
              {evaluate && q.answer_id && (
                <div className="flex flex-wrap gap-2">
                  {q.status === "review" && <Button size="sm" onClick={() => accept(q)}>Accept {q.score ?? 0}</Button>}
                  <Button size="sm" variant="outline" onClick={() => setMark(q)}>Mark or change the mark</Button>
                  {(q.type === "short" || q.type === "long") && <Button size="sm" variant="ghost" onClick={() => markAgain(q)}>Mark with AI again</Button>}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>Proctoring</CardTitle></CardHeader>
        <CardContent className="grid gap-4 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={["high", "critical"].includes(p.risk_level) ? "destructive" : "secondary"}>Risk: {RISK[p.risk_level]}</Badge>
            <span>{p.violations} warning(s)</span>
            {Object.entries(p.counts).map(([k, n]) => <Badge key={k} variant="outline">{words(k)}: {n}</Badge>)}
            {rep.plagiarism.level !== "clear" && <Badge variant="destructive">Answers similar to others: {rep.plagiarism.level}</Badge>}
          </div>
          {p.events.length > 0 && (
            <div className="grid gap-1" data-testid="timeline">
              <b>Timeline</b>
              {p.events.map((e, i) => <div key={i} className="flex gap-3"><span className="w-24 font-mono text-xs text-muted-foreground">{time(e.at)}</span><span>{words(e.type)}{e.duration_ms ? ` (${Math.round(e.duration_ms / 1000)} s)` : ""}</span></div>)}
            </div>
          )}
          <div className="grid gap-2">
            <div className="flex items-center gap-3">
              <b>Camera pictures ({pics.length})</b>
              {problems.length > 0 && <Button size="sm" variant="outline" onClick={() => { setOnlyProblems(!onlyProblems); setShown(24) }}>{onlyProblems ? `Show all pictures` : `Show only the ${problems.length} with a problem`}</Button>}
            </div>
            <div className="flex flex-wrap gap-2" data-testid="pictures">
              {pics.slice(0, shown).map((s) => (
                <figure key={s.id} className="grid gap-0.5 text-xs text-muted-foreground">
                  <Snapshot id={s.id} alt={`Camera picture at ${time(s.at)}`} className="h-24 w-32" />
                  <figcaption>{time(s.at)}{s.faces !== 1 ? ` · ${s.faces ?? "?"} face(s)` : ""}</figcaption>
                </figure>
              ))}
              {!pics.length && <span className="text-muted-foreground">No pictures.</span>}
            </div>
            {pics.length > shown && <div><Button size="sm" variant="ghost" onClick={() => setShown(shown + 24)}>Show more</Button></div>}
          </div>
        </CardContent>
      </Card>

      {mark && <MarkDialog q={mark} onClose={() => setMark(null)} onSaved={load} />}
    </div>
  )
}
