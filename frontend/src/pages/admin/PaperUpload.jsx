import { useRef, useState } from "react"
import { toast } from "sonner"
import { Check, CheckCircle2, Circle, Loader2, TriangleAlert, Upload, X, XCircle } from "lucide-react"
import { api } from "@/lib/api"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { Html } from "@/pages/candidate/questions"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"

const STEPS = [["read", "Reading the file"], ["ai", "Understanding the questions"], ["check", "Checking every question"]]
const ACCEPT = ".pdf,.docx,.xlsx,.csv,.txt,.md,.jpg,.jpeg,.png,.webp"
const key = (si, qi) => `${si}:${qi}`

// Lines the review shows for each question: the server's checked version (view) for a good one, the AI's own words for one with a problem.
function Row({ q, on, toggle, n }) {
  const v = q.view
  return (
    <div className={"grid gap-2 rounded-md border p-3 " + (q.ok ? "" : "border-destructive/40 bg-destructive/5")} data-testid="paper-question" data-ok={q.ok}>
      <div className="flex flex-wrap items-center gap-2">
        <Checkbox checked={on} disabled={!q.ok} onCheckedChange={toggle} aria-label={`Include question ${n}`} />
        <span className="font-medium">{n}. {v?.title ?? q.item?.title ?? "Question"}</span>
        <Badge variant="secondary">{TYPE_LABEL[v?.type ?? q.item?.type] ?? "Question"}</Badge>
        {v && <span className="text-xs text-muted-foreground">{v.marks} {v.marks === 1 ? "mark" : "marks"}</span>}
        {v?.answer_from_ai && <Badge className="border-amber-300 bg-amber-100 text-amber-900" data-testid="ai-answer">Answer chosen by AI, check it</Badge>}
      </div>
      {v ? <Html html={v.body} /> : <p className="whitespace-pre-wrap text-sm">{String(q.item?.statement ?? "")}</p>}
      {v?.options && (
        <ul className="grid gap-1.5">
          {v.options.map((o, i) => (
            <li key={i} className={"flex items-start gap-2 rounded border p-1.5 text-sm " + (o.correct ? "border-green-300 bg-green-50" : "")}>
              {o.correct ? <Check className="mt-0.5 size-4 shrink-0 text-green-700" aria-label="Correct answer" /> : <span className="size-4 shrink-0" />}
              <span className="grid gap-1">{o.text && <span>{o.text}</span>}{o.image && <img src={o.image} alt={`Picture of option ${i + 1}`} className="max-h-24 w-auto max-w-full rounded border bg-white object-contain" />}</span>
            </li>
          ))}
        </ul>
      )}
      {v?.model_answer && <p className="text-sm"><span className="font-medium">Model answer:</span> {v.model_answer.length > 300 ? v.model_answer.slice(0, 300) + "..." : v.model_answer}</p>}
      {v?.cases != null && <p className="text-sm text-muted-foreground">{v.cases} test cases {v.type === "sql" ? "(datasets)" : ""}, checked by running the AI's solution.</p>}
      {q.probs.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-destructive" data-testid="paper-problems">{q.probs.map((m, i) => <li key={i}>{m}</li>)}</ul>
      )}
    </div>
  )
}

// Upload a question paper: the server reads it, the AI writes the question file, the ordinary check runs, and the examiner reviews before anything is saved.
export default function PaperUpload({ test, onImported, onClose }) {
  const [phase, setPhase] = useState("")          // "" | read | ai | check | done
  const [failed, setFailed] = useState("")        // the step that stopped
  const [error, setError] = useState("")
  const [info, setInfo] = useState({})            // what the first step found
  const [seconds, setSeconds] = useState(0)
  const [result, setResult] = useState(null)      // { pack, report, notes }
  const [include, setInclude] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const ctl = useRef(null)
  const clock = useRef(null)
  const input = useRef(null)

  const running = !!phase && phase !== "done" && !failed
  const stop = () => { ctl.current?.abort(); clearInterval(clock.current) }

  async function start(file) {
    if (!file) return
    stop()
    ctl.current = new AbortController()
    const { signal } = ctl.current
    setResult(null); setError(""); setFailed(""); setInfo({}); setSeconds(0)
    let at = "read"
    try {
      setPhase("read")
      const form = new FormData()
      form.append("file", file)
      const paper = await api(`/tests/${test.id}/read-paper`, { form, signal })
      setInfo({ kind: paper.kind, pages: paper.pages, pictures: paper.images.length, scans: paper.scans.length })
      at = "ai"
      setPhase("ai")
      const t0 = Date.now()
      clock.current = setInterval(() => setSeconds(Math.round((Date.now() - t0) / 1000)), 500)
      const body = { text: paper.text, images: paper.images.map(({ id, src }) => ({ id, src })), scans: paper.scans }
      const ai = await api(`/tests/${test.id}/understand-paper`, { method: "POST", body, signal })
      clearInterval(clock.current)
      at = "check"
      setPhase("check")
      const report = await api(`/tests/${test.id}/import-questions`, { method: "POST", body: { pack: ai.pack, dry_run: true, detail: true }, signal })
      const rows = review(ai.pack, report)
      setInclude(new Set(rows.flatMap((s) => s.questions.filter((q) => q.ok).map((q) => key(q.si, q.qi)))))
      setResult({ pack: ai.pack, report, rows, notes: [...paper.notes, ...ai.notes] })
      setPhase("done")
    } catch (e) {
      clearInterval(clock.current)
      if (e.name === "AbortError") { setPhase(""); return }
      setFailed(at)
      setError(e.message)
    }
  }

  function cancel() { stop(); setPhase(""); setFailed(""); setError("") }

  async function importChosen() {
    const { pack } = result
    const chosen = { ...pack, sections: pack.sections.map((s, si) => ({ ...s, questions: (s.questions ?? []).filter((_, qi) => include.has(key(si, qi))) })).filter((s) => s.questions.length) }
    setBusy(true)
    try {
      const exam = await api(`/tests/${test.id}/import-questions`, { method: "POST", body: { pack: chosen, dry_run: false } })
      toast.success(`${include.size} questions added. Fix any wording with the pencil in the Questions tab.`)
      onImported(exam)
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const toggle = (k) => setInclude((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const stepOf = (k) => STEPS.findIndex(([x]) => x === k)
  const detail = { read: info.kind ? `${info.kind} file${info.pages ? `, ${info.pages} ${info.pages === 1 ? "page" : "pages"}` : ""}, ${info.pictures} ${info.pictures === 1 ? "picture" : "pictures"} found` : "", ai: phase === "ai" ? `${seconds} s (usually 20 to 90 seconds)` : "", check: "" }

  return (
    <section className="grid gap-3" data-testid="paper-upload">
      <h3 className="font-medium">Upload your question paper</h3>
      <p className="text-sm text-muted-foreground">A PDF, Word (.docx), Excel (.xlsx), Notepad (.txt) file or a photo. The questions, answers, marks and pictures are found for you, and nothing is added until you press Import.</p>

      {!running && phase !== "done" && (
        <div className="flex flex-wrap items-center gap-3">
          <input ref={input} type="file" accept={ACCEPT} className="hidden" aria-label="Question paper file" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; start(f) }} />
          <Button onClick={() => input.current.click()}><Upload /> Choose question paper</Button>
          <span className="text-xs text-muted-foreground">Up to 20 MB, about 40 questions at a time.</span>
        </div>
      )}

      {phase && (
        <div className="grid gap-2 rounded-lg border bg-muted/40 p-3" role="status" aria-live="polite" data-testid="paper-steps">
          {STEPS.map(([k, label], i) => {
            const state = failed === k ? "fail" : stepOf(phase) > i || phase === "done" ? "done" : phase === k ? "run" : "wait"
            return (
              <div key={k} className="flex items-center gap-2 text-sm" data-state={state}>
                {state === "done" ? <CheckCircle2 className="size-4 text-green-600" /> : state === "run" ? <Loader2 className="size-4 animate-spin text-primary" /> : state === "fail" ? <XCircle className="size-4 text-destructive" /> : <Circle className="size-4 text-muted-foreground" />}
                <span className={state === "wait" ? "text-muted-foreground" : "font-medium"}>{label}</span>
                <span className="text-xs text-muted-foreground">{state === "wait" ? "" : detail[k]}</span>
              </div>
            )
          })}
          {phase === "done" && <p className="text-sm font-medium text-green-700">Completed. Review the questions below.</p>}
          {running && <div><Button variant="outline" size="sm" onClick={cancel}><X /> Cancel</Button></div>}
        </div>
      )}

      {error && <Alert variant="destructive" className="p-3" data-testid="paper-error">{error}</Alert>}

      {result && (
        <div className="grid gap-3" data-testid="paper-review">
          {result.notes.length > 0 && (
            <Alert className="border-amber-300 bg-amber-50 p-3 text-amber-900" data-testid="paper-notes">
              <p className="flex items-center gap-1 font-medium"><TriangleAlert className="size-4" /> Please read</p>
              <ul className="list-disc pl-5">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </Alert>
          )}
          {!result.report.ok && !result.report.problems.length && <Alert variant="destructive" className="p-3">{result.report.errors.join(" ")}</Alert>}
          <p className="text-sm font-medium">{result.report.total_questions} of {result.rows.reduce((n, s) => n + s.questions.length, 0)} questions are ready. {include.size} will be added.</p>
          {result.rows.map((s, si) => (
            <div key={si} className="grid gap-2" data-testid="paper-section">
              <h4 className="font-medium">{s.title}</h4>
              {s.questions.map((q, qi) => <Row key={qi} q={q} n={qi + 1} on={include.has(key(si, qi))} toggle={() => toggle(key(si, qi))} />)}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={busy || !include.size} onClick={importChosen}>{busy ? "Importing..." : `Import ${include.size} questions`}</Button>
            <Button variant="outline" onClick={() => { setResult(null); setPhase("") }}>Start again with another file</Button>
            <span className="text-xs text-muted-foreground">Questions with a problem cannot be added. Fix the paper and upload it again, or add them by hand.</span>
          </div>
        </div>
      )}
    </section>
  )
}

// The AI's file next to the server's check: every question of the file, good ones with the server's version, bad ones with their problems.
function review(pack, report) {
  const problems = report.problems ?? []
  let next = 0
  return (pack.sections ?? []).map((sec, si) => {
    const broken = problems.some((p) => p.section === si + 1 && p.question == null)
    const checked = broken ? null : report.sections[next++]
    let seen = 0
    return {
      title: (typeof sec?.title === "string" && sec.title) || `Section ${si + 1}`,
      questions: (Array.isArray(sec?.questions) ? sec.questions : []).map((item, qi) => {
        const probs = problems.filter((p) => p.section === si + 1 && p.question === qi + 1).map((p) => p.message)
        return { si, qi, item, probs, ok: !probs.length && !!checked, view: !probs.length ? checked?.questions[seen++] : null }
      }),
    }
  })
}
