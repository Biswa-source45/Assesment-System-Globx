import { useState } from "react"
import { toast } from "sonner"
import { Copy, Sparkles } from "lucide-react"
import { post } from "@/lib/api"
import { useDepartments } from "@/lib/useDepartments"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import PaperUpload from "@/pages/admin/PaperUpload"

const MAX_BYTES = 2_000_000

// An AI chat often wraps the JSON in a sentence or a ```json fence; take what lies between the first { and the last }.
export function parsePack(text) {
  const start = text.indexOf("{"), end = text.lastIndexOf("}")
  if (start < 0 || end < start) throw new Error("This file does not contain a JSON document.")
  try {
    return JSON.parse(text.slice(start, end + 1))
  } catch (e) {
    throw new Error(`The file is not valid JSON: ${e.message}`)
  }
}

// What the server's check of a file says: every problem, or what would be created. `trial` = the Help playground (nothing to import).
export function PackReport({ report, trial = false }) {
  if (!report) return null
  if (!report.ok) {
    return (
      <Alert variant="destructive" className="p-3" data-testid="pack-errors">
        <p className="font-medium">{report.errors.length} problem(s) found. {trial ? "" : "Nothing was added. "}Fix the file, or ask the AI to fix these, and {trial ? "check" : "upload"} it again:</p>
        <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5">{report.errors.map((m, i) => <li key={i}>{m}</li>)}</ul>
      </Alert>
    )
  }
  return (
    <div className="grid gap-2" data-testid="pack-preview">
      <p className="text-sm font-medium">{report.total_questions} questions, {report.total_marks} marks, in {report.sections.length} sections. {trial ? "This file is correct and would import." : "Check them, then import."}</p>
      <div className="grid max-h-56 gap-2 overflow-auto">
        {report.sections.map((s, i) => (
          <div key={i} className="rounded-md border p-2 text-sm" data-testid="pack-section">
            <p className="font-medium">{s.title}{s.timer_min ? ` (${s.timer_min} min)` : ""} <span className="font-normal text-muted-foreground">{s.count} {s.count === 1 ? "question" : "questions"}, {s.marks} {s.marks === 1 ? "mark" : "marks"}</span></p>
            {s.questions.map((q, j) => (
              <div key={j} className="mt-1 flex items-center gap-2">
                <span className="grow">{q.title}</span>
                <Badge variant="secondary">{TYPE_LABEL[q.type]}</Badge>
                <span className="w-14 text-right text-xs text-muted-foreground">{q.marks} {q.marks === 1 ? "mark" : "marks"}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

// Step 1: the app writes the prompt (exam details + how many questions of each type). Step 2: the JSON the AI answered with is checked and,
// if it is all correct, imported. Nothing is saved until the examiner presses Import.
export default function QuestionPack({ test, onClose, onImported }) {
  const { departments } = useDepartments()
  const dept = departments?.find((d) => d.id === test.department_id)
  const offered = dept?.question_types ?? Object.keys(TYPE_LABEL)
  const [counts, setCounts] = useState(() => ({ mcq_single: 5 }))
  const [prompt, setPrompt] = useState("")
  const [pack, setPack] = useState(null)
  const [report, setReport] = useState(null)  // the server's dry-run answer: { ok, errors, sections, total_questions, total_marks }
  const [fileError, setFileError] = useState("")
  const [pasted, setPasted] = useState("")
  const [busy, setBusy] = useState(false)

  const total = offered.reduce((n, t) => n + (Number(counts[t]) || 0), 0)

  async function makePrompt() {
    setBusy(true)
    try {
      const body = Object.fromEntries(offered.map((t) => [t, Number(counts[t]) || 0]))
      setPrompt((await post(`/tests/${test.id}/question-prompt`, body)).prompt)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(prompt)
      toast.success("Prompt copied")
    } catch {
      toast.error("The browser blocked copying. Select the text in the box and copy it.")  // plain http, for example
    }
  }

  // Both ways in (a file, or the AI's reply pasted as text) end here: parse, let the server check everything, show the result.
  async function check(text) {
    setPack(null)
    setReport(null)
    setFileError("")
    if (text.length > MAX_BYTES) return setFileError("The JSON is too large (2 MB at most).")
    setBusy(true)
    try {
      const parsed = parsePack(text)
      setReport(await post(`/tests/${test.id}/import-questions`, { pack: parsed, dry_run: true }))
      setPack(parsed)
    } catch (err) {
      setFileError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function chooseFile(e) {
    const file = e.target.files?.[0]
    setPasted("")
    if (file) await check(await file.text())
    else { setPack(null); setReport(null); setFileError("") }
  }

  async function importAll() {
    setBusy(true)
    try {
      const exam = await post(`/tests/${test.id}/import-questions`, { pack, dry_run: false })
      toast.success(`${report.total_questions} questions added in ${report.sections.length} sections`)
      onImported(exam)
      onClose()
    } catch (e) {
      setFileError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Build "{test.title}" with AI</DialogTitle>
          <DialogDescription>Upload the question paper you already have and the AI turns it into questions. <a className="underline" href="/admin/help?topic=paper-upload" target="_blank" rel="noreferrer">How it works</a></DialogDescription>
        </DialogHeader>

        <PaperUpload test={test} onImported={onImported} onClose={onClose} />

        <details className="rounded-lg border p-3" data-testid="json-route">
          <summary className="cursor-pointer font-medium">Or make the question file yourself with ChatGPT or Claude</summary>
          <p className="mt-2 text-sm text-muted-foreground">Get a prompt, give it to ChatGPT or Claude with your question set, then upload the JSON file it gives you. <a className="underline" href="/admin/help?topic=json-route" target="_blank" rel="noreferrer">Format help and samples</a></p>
        <div className="mt-3 grid gap-4">
        <section className="grid gap-3">
          <h3 className="font-medium">1. Get the prompt</h3>
          <p className="text-sm text-muted-foreground">It already contains this exam's department, title, description, instructions, time and rules. Say how many questions of each type you need.</p>
          <div className="flex flex-wrap items-end gap-3">
            {offered.map((t) => (
              <div key={t} className="grid gap-1">
                <Label htmlFor={`count-${t}`} className="text-xs font-normal">{TYPE_LABEL[t]}</Label>
                <Input id={`count-${t}`} className="w-24" type="number" min="0" max="200" value={counts[t] ?? 0}
                  onChange={(e) => { setCounts({ ...counts, [t]: e.target.value }); setPrompt("") }} />
              </div>
            ))}
            <Button disabled={busy || total < 1} onClick={makePrompt}><Sparkles /> Create prompt</Button>
          </div>
          {prompt && (
            <div className="grid gap-2">
              <Textarea readOnly aria-label="AI prompt" className="h-40 font-mono text-xs" value={prompt} onFocus={(e) => e.target.select()} />
              <div><Button variant="outline" size="sm" onClick={copy}><Copy /> Copy prompt</Button></div>
            </div>
          )}
        </section>

        <section className="grid gap-3">
          <h3 className="font-medium">2. Give the AI's answer: upload the file, or paste the text</h3>
          <Input type="file" accept=".json,.txt,application/json" aria-label="Questions JSON file" onChange={chooseFile} />
          <p className="text-sm text-muted-foreground">Some AI chats show the JSON on screen instead of giving a file. Copy it and paste it here.</p>
          <Textarea aria-label="Pasted JSON" className="h-28 font-mono text-xs" placeholder='Paste the JSON here, for example {"sections": [ ... ]}' value={pasted}
            onChange={(e) => setPasted(e.target.value)} />
          <div><Button variant="outline" size="sm" disabled={busy || !pasted.trim()} onClick={() => check(pasted)}>Check pasted JSON</Button></div>
          {fileError && <Alert variant="destructive" className="p-3" data-testid="pack-file-error">{fileError}</Alert>}
          <PackReport report={report} />
        </section>
        </div>
        </details>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          {report?.ok && <Button disabled={busy} onClick={importAll}>{busy ? "Importing..." : `Import ${report.total_questions} questions`}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
