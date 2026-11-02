import { useState } from "react"
import CodeMirror from "@uiw/react-codemirror"
import { EditorView } from "@codemirror/view"
import { python } from "@codemirror/lang-python"
import { java } from "@codemirror/lang-java"
import { javascript } from "@codemirror/lang-javascript"
import { cpp } from "@codemirror/lang-cpp"
import { get, post } from "@/lib/api"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

// Question bodies are sanitised on the server before they are stored.
export const Html = ({ html }) => <div className="q-html" dangerouslySetInnerHTML={{ __html: html || "" }} />

export function McqView({ q, r, onChange, closed }) {
  const selected = r.selected ?? []
  if (!q.multi) {
    return (
      <RadioGroup value={selected[0] ?? ""} onValueChange={(v) => onChange({ selected: [v] }, true)} disabled={closed} className="gap-2">
        {q.options.map((o) => (
          <Label key={o.id} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-secondary">
            <RadioGroupItem value={o.id} /> {o.text}
          </Label>
        ))}
      </RadioGroup>
    )
  }
  const toggle = (id) => onChange({ selected: selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id] }, true)
  return (
    <div className="grid gap-2">
      {q.options.map((o) => (
        <Label key={o.id} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-secondary">
          <Checkbox checked={selected.includes(o.id)} disabled={closed} onCheckedChange={() => toggle(o.id)} /> {o.text}
        </Label>
      ))}
      <p className="text-xs text-muted-foreground">More than one answer can be correct. Choosing more options than there are correct answers scores negative.</p>
    </div>
  )
}

export const wordCount = (t) => (t || "").trim().split(/\s+/).filter(Boolean).length

export function TextView({ q, r, onChange, closed }) {
  const words = wordCount(r.text)
  return (
    <div className="grid gap-1.5">
      <Textarea
        aria-label="Your answer"
        value={r.text ?? ""}
        disabled={closed}
        onChange={(e) => onChange({ text: e.target.value })}
        className={q.type === "long" ? "min-h-64" : "min-h-32"}
        placeholder="Type your answer here"
      />
      <div className={"text-xs " + (q.max_words && words > q.max_words ? "text-destructive" : "text-muted-foreground")}>
        {words} words{q.max_words ? ` (limit ${q.max_words})` : ""}
      </div>
    </div>
  )
}

const LANG_EXT = { python: python, java: java, javascript: javascript, c: cpp, cpp: cpp }

export function CodeView({ q, r, onChange, attemptId, closed, blockPaste }) {
  const langs = q.languages
  const lang = langs.some((l) => l.key === r.language) ? r.language : langs[0]?.key
  const [sources, setSources] = useState({ [lang]: r.source ?? q.starter?.[lang] ?? "" })
  const [custom, setCustom] = useState(q.open_cases[0]?.input ?? "")
  const [busy, setBusy] = useState("")
  const [res, setRes] = useState(null)
  const src = sources[lang] ?? q.starter?.[lang] ?? ""

  const setSrc = (v) => { setSources((s) => ({ ...s, [lang]: v })); onChange({ language: lang, source: v }) }
  const pickLang = (k) => { onChange({ language: k, source: sources[k] ?? q.starter?.[k] ?? "" }, true) }

  async function exec(kind) {
    setBusy(kind)
    setRes(null)
    try {
      const out = await post(`/attempts/${attemptId}/code/${q.id}/${kind}`, {
        language: lang, source: src, custom_input: kind === "run" && custom.trim() ? custom : undefined,
      })
      let s
      for (let i = 0; i < 120; i++) {
        s = await get(`/submissions/${out.submission_id}`)
        if (s.status === "done" || s.status === "error") break
        await new Promise((z) => setTimeout(z, i < 10 ? 400 : 900))
      }
      setRes(s)
      if (kind === "submit" && s.status === "done") onChange({ language: lang, source: src, submitted: true }, true)
    } catch (e) {
      setRes({ status: "error", result: { error: e.message } })
    } finally {
      setBusy("")
    }
  }

  const extensions = [
    LANG_EXT[lang]?.() ?? [],
    EditorView.lineWrapping,
    ...(blockPaste ? [EditorView.domEventHandlers({ paste: (e) => { e.preventDefault(); return true }, drop: (e) => { e.preventDefault(); return true } })] : []),
  ]
  const result = res?.result

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={lang} onValueChange={pickLang} disabled={closed}>
          <SelectTrigger className="w-52" aria-label="Language"><SelectValue /></SelectTrigger>
          <SelectContent>{langs.map((l) => <SelectItem key={l.key} value={l.key}>{l.name}</SelectItem>)}</SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">Time limit {q.time_limit_ms / 1000}s per case, memory {q.memory_mb} MB</span>
      </div>
      {!langs.length && <Alert variant="destructive" className="p-3">No language for this question is installed on the server. Tell the invigilator.</Alert>}
      <div className="overflow-hidden rounded-lg border" data-testid="code-editor">
        <CodeMirror value={src} height="340px" extensions={extensions} editable={!closed} onChange={setSrc}
          basicSetup={{ foldGutter: false }} theme="light" />
      </div>
      <div className="flex gap-2">
        <Button variant="outline" disabled={!!busy || closed || !langs.length} onClick={() => exec("run")}>{busy === "run" ? "Running..." : "Run on samples"}</Button>
        <Button disabled={!!busy || closed || !langs.length} onClick={() => exec("submit")}>{busy === "submit" ? "Judging..." : "Submit"}</Button>
      </div>
      <Tabs defaultValue="results">
        <TabsList>
          <TabsTrigger value="results">Test results</TabsTrigger>
          <TabsTrigger value="input">Custom input</TabsTrigger>
        </TabsList>
        <TabsContent value="input" className="grid gap-2">
          <Label htmlFor={`custom-${q.id}`} className="text-xs text-muted-foreground">Input for "Run on samples" (optional)</Label>
          <Textarea id={`custom-${q.id}`} className="font-mono text-xs" value={custom} onChange={(e) => setCustom(e.target.value)} />
          {result?.custom && (
            <pre className="whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">{result.custom.verdict}: {result.custom.stdout}{result.custom.stderr}</pre>
          )}
        </TabsContent>
        <TabsContent value="results" className="grid gap-2 text-sm" data-testid="code-results">
          {!res && <p className="text-muted-foreground">Run checks the sample cases. Submit checks every case, including hidden ones, and is what counts.</p>}
          {res?.status === "error" && <Alert variant="destructive" className="p-3">{result?.error}</Alert>}
          {result?.compile && !result.compile.ok && <Alert variant="destructive" className="p-3"><pre className="whitespace-pre-wrap text-xs">{result.compile.message}</pre></Alert>}
          {result?.open?.map((c) => (
            <details key={c.ordinal} className="rounded-md border p-2">
              <summary className="flex cursor-pointer items-center gap-2">
                Sample {c.ordinal} <Badge variant={c.passed ? "default" : "destructive"} className={c.passed ? "bg-green-600" : ""}>{c.verdict}</Badge>
                <span className="text-xs text-muted-foreground">{c.time_ms ?? 0} ms</span>
              </summary>
              <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
                {[["Input", c.input], ["Expected", c.expected], ["Your output", c.stdout]].map(([label, v]) => (
                  <div key={label}><div className="text-muted-foreground">{label}</div><pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted p-1.5">{(v ?? "").slice(0, 1500)}</pre></div>
                ))}
              </div>
              {c.stderr && <pre className="mt-2 whitespace-pre-wrap text-xs text-destructive">{c.stderr}</pre>}
            </details>
          ))}
          {result?.hidden && result.hidden.total > 0 && (
            <p>Hidden cases passed: <b>{result.hidden.passed} / {result.hidden.total}</b></p>
          )}
          {res?.status === "done" && res.kind === "submit" && <p className="font-medium">Score {result.score} / {result.max_score}</p>}
        </TabsContent>
      </Tabs>
    </div>
  )
}
