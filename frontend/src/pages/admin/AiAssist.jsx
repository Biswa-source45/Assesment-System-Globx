import { useRef, useState } from "react"
import { Sparkles, Undo2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { fileToDataUrl, pastedImage } from "@/lib/image"
import { QuestionPictures } from "@/components/PicturePicker"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

// "Write or change this question with AI". The AI never saves: its answer fills the editor below, the author reads it and presses Save.
// `blank`: nothing typed yet (the AI writes a new question); otherwise it changes the question as it is now.
export default function AiAssist({ form, blank, types, current, apply, restore, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const [prompt, setPrompt] = useState("")
  const [images, setImages] = useState([])
  const [kind, setKind] = useState("auto")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState(null)
  const [undo, setUndo] = useState(null)  // the form as it was before the last AI answer
  const abort = useRef(null)

  async function pastePicture(e) {
    const file = pastedImage(e)
    if (!file) return
    e.preventDefault()
    if (images.length >= 4) return toast.error("Up to 4 pictures.")
    try { const src = await fileToDataUrl(file); setImages((x) => [...x, src]) } catch (err) { toast.error(err.message) }
  }

  async function run() {
    setError("")
    let cur
    try { cur = blank ? undefined : current() } catch (e) { return setError(e.message) }  // e.g. the SQL tables are not valid yet
    abort.current = new AbortController()
    setBusy(true)
    try {
      const out = await api("/questions/ai-draft", { method: "POST", signal: abort.current.signal,
        body: { department_id: form.department_id, type: blank && kind !== "auto" ? kind : null, prompt, images, current: cur } })
      setUndo(form)
      apply(out.question)
      setResult(out)
      setPrompt("")
      setImages([])
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function undoLast() {
    restore(undo)
    setUndo(null)
    setResult(null)
  }

  if (!open) {
    return <div><Button variant="outline" onClick={() => setOpen(true)}><Sparkles /> Write or change this question with AI</Button></div>
  }
  return (
    <Card data-testid="ai-assist">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sparkles className="size-5 text-primary" /> {blank ? "Write a question with AI" : "Change this question with AI"}</CardTitle>
        <CardDescription>
          {blank
            ? "Say what the question should be, or add a picture of a question (a photo, a screenshot), or both. The AI fills the form below; nothing is saved until you press Save question."
            : "Say what to change, for example \"make it harder\", \"add a fifth option\" or \"the answer is C\". Everything else stays as it is. Nothing is saved until you press Save question."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {blank && (
          <div className="flex items-center gap-2">
            <span className="text-sm">Type</span>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger className="w-60" aria-label="Type of question to write"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Let the AI choose</SelectItem>
                {types.map((t) => <SelectItem key={t} value={t}>{TYPE_LABEL[t]}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        )}
        <Textarea aria-label="Tell the AI what you want" className="min-h-24" maxLength={4000} value={prompt} onChange={(e) => setPrompt(e.target.value)} onPaste={pastePicture} disabled={busy}
          placeholder={blank ? "For example: an easy question on percentages for a finance clerk, with four options" : "For example: make the question harder and add a fifth option"} />
        <QuestionPictures name="request" images={images} onChange={setImages} hint={blank ? "A picture of a question for the AI to read. You can also paste a screenshot into the box. Up to 4." : "A picture for the AI to look at or use. You can also paste a screenshot into the box. Up to 4."} />
        {error && <Alert variant="destructive" className="p-3" data-testid="ai-error">{error}</Alert>}
        <div className="flex items-center gap-2">
          <Button onClick={run} disabled={busy || (!prompt.trim() && (!blank || !images.length))}>{busy ? "The AI is working..." : blank ? "Write question" : "Change question"}</Button>
          {busy && <Button variant="outline" onClick={() => abort.current?.abort()}>Cancel</Button>}
          {busy && <span className="text-xs text-muted-foreground" role="status">Reading your request and checking the answer. This can take up to a minute.</span>}
          {undo && !busy && <Button variant="outline" onClick={undoLast}><Undo2 /> Undo the last AI change</Button>}
        </div>
        {result && !busy && (
          <div className="grid gap-2 text-sm" data-testid="ai-result">
            {result.changes?.length > 0 && <div><p className="font-medium">What the AI did</p><ul className="list-disc pl-5">{result.changes.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
            {result.warnings?.map((w, i) => <div key={i} role="alert" data-testid="ai-warning" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900">{w}</div>)}
            {result.notes?.length > 0 && <ul className="list-disc pl-5 text-muted-foreground">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
            <p className="text-xs text-muted-foreground">Read the question and its answer below before you save. The AI can be wrong.</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
