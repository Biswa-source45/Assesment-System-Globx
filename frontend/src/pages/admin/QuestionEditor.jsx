import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { Plus, Sparkles, Trash2 } from "lucide-react"
import { get, post, put } from "@/lib/api"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { Verdict } from "@/pages/candidate/CodeView"
import SqlBuilder from "@/pages/admin/SqlBuilder"
import { buildInserts, buildSchema, checkTables } from "@/lib/sqlbuild"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

const TYPES = ["mcq_single", "mcq_multi", "short", "long", "coding", "sql"]
const DEFAULT_MARKS = { mcq_single: 1, mcq_multi: 1, short: 2, long: 5, coding: 10, sql: 10 }
const LANGS = [["python", "Python"], ["java", "Java"], ["javascript", "JavaScript"], ["cpp", "C++"], ["c", "C"]]
const rid = () => Math.random().toString(36).slice(2, 8)
const blankOptions = () => Array.from({ length: 4 }, () => ({ id: rid(), text: "", correct: false }))

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")
// Plain text becomes paragraphs; text that already contains HTML tags is sent as it is (the server sanitises it).
const toHtml = (t) => (/<[a-z][\s\S]*>/i.test(t) ? t : t.split(/\n{2,}/).filter((p) => p.trim()).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join(""))
const fromHtml = (h) => (/^(<p>[^<]*(<br>[^<]*)*<\/p>)*$/.test(h || "") ? unesc((h || "").replace(/<\/p><p>/g, "\n\n").replace(/<br>/g, "\n").replace(/<\/?p>/g, "")) : h)

const blank = () => ({
  type: "mcq_single", title: "", body: "", difficulty: "medium", marks: 1, negative_marks: 0, skills: "",
  options: blankOptions(), model_answer: "", keywords: "", max_words: 150,
  languages: ["python"], time_limit_ms: 2000, memory_mb: 256, constraints: "", ref_lang: "python", ref_source: "", cases: [],
  tables: [], datasets: [], reference_sql: "", ordered: false, preview: null,  // SQL questions
})

function fromQuestion(q) {
  const c = q.config ?? {}
  return {
    ...blank(), type: q.type, title: q.title, body: fromHtml(q.body), difficulty: q.difficulty, marks: q.marks, negative_marks: q.negative_marks,
    skills: (q.skills ?? []).join(", "),
    options: q.type.startsWith("mcq") ? (c.options ?? []).map((o) => ({ id: o.id, text: o.text, correct: !!o.correct })) : blankOptions(),
    model_answer: c.model_answer ?? "", keywords: (c.keywords ?? []).join(", "), max_words: c.max_words ?? (q.type === "short" ? 150 : 800),
    languages: c.languages ?? ["python"], time_limit_ms: c.time_limit_ms ?? 2000, memory_mb: c.memory_mb ?? 256, constraints: c.constraints ?? "",
    ref_lang: c.reference?.language ?? "python", ref_source: c.reference?.source ?? "",
    cases: (q.cases ?? []).map((k) => ({ input: k.input, expected: k.expected, visibility: k.visibility, weight: k.weight, purpose: k.purpose ?? "" })),
  }
}

// An existing SQL question comes back as tables and rows (built by the server from its schema and datasets).
function withSql(f, q) {
  if (q.type !== "sql") return f
  const tables = (q.sql_tables?.[0] ?? []).map((t) => ({ name: t.name, columns: t.columns.map((c, i) => ({ name: c, type: t.types[i] })) }))
  const datasets = q.cases.map((c, i) => ({
    visibility: c.visibility, weight: c.weight, purpose: c.purpose ?? "",
    rows: tables.map((_, ti) => (q.sql_tables[i]?.[ti]?.rows ?? []).map((r) => r.map((v) => (v === null ? "" : String(v))))),
  }))
  const preview = q.cases.map((c) => (c.expected ? { ok: true, ...JSON.parse(c.expected) } : null))
  return { ...f, tables, datasets, preview, reference_sql: q.config?.reference_sql ?? "", ordered: !!q.config?.ordered }
}

export default function QuestionEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [f, setF] = useState(blank)
  const [check, setCheck] = useState(null)  // verdict per case from "Check reference solution"
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const isMcq = f.type.startsWith("mcq")
  const isText = f.type === "short" || f.type === "long"

  useEffect(() => {
    if (id === "new") return
    get(`/questions/${id}`).then((q) => setF(withSql(fromQuestion(q), q))).catch((e) => setError(e.message))
  }, [id])

  function pickType(t) {
    setF((x) => ({ ...x, type: t, marks: DEFAULT_MARKS[t], max_words: t === "short" ? 150 : 800 }))
  }

  const setOption = (i, patch) => set("options", f.options.map((o, j) => (j === i ? { ...o, ...patch } : o)))
  const setCase = (i, patch) => { setCheck(null); set("cases", f.cases.map((c, j) => (j === i ? { ...c, ...patch } : c))) }

  function sqlPayload() {
    const bad = checkTables(f.tables)
    if (bad) throw new Error(bad)
    return {
      type: "sql", title: f.title, body: toHtml(f.body), difficulty: f.difficulty, marks: Number(f.marks), negative_marks: 0,
      skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean), status: "approved",
      config: { schema: buildSchema(f.tables), seed: "", engines: ["sqlite"], ordered: f.ordered, reference_sql: f.reference_sql },
      cases: f.datasets.map((d, i) => ({ ordinal: i + 1, visibility: d.visibility, input: buildInserts(f.tables, d.rows), expected: "", weight: Number(d.weight) || 1, purpose: d.purpose })),
    }
  }

  function payload() {
    if (f.type === "sql") return sqlPayload()
    const config = {}
    if (isMcq) { config.options = f.options.filter((o) => o.text.trim()).map((o) => ({ id: o.id, text: o.text.trim(), correct: !!o.correct })); config.partial = true }
    if (isText) {
      config.model_answer = f.model_answer
      config.max_words = Number(f.max_words) || 150
      if (f.type === "short") config.keywords = f.keywords.split(",").map((s) => s.trim()).filter(Boolean)
      else config.allow_file = false
    }
    if (f.type === "coding") {
      Object.assign(config, { languages: f.languages, time_limit_ms: Number(f.time_limit_ms), memory_mb: Number(f.memory_mb), constraints: f.constraints, comparator: "trim" })
      if (f.ref_source.trim()) config.reference = { language: f.ref_lang, source: f.ref_source }
    }
    return {
      type: f.type, title: f.title, body: toHtml(f.body), difficulty: f.difficulty, marks: Number(f.marks), negative_marks: Number(f.negative_marks),
      skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean), status: "approved", config,
      cases: f.type === "coding" ? f.cases.map((c, i) => ({ ordinal: i + 1, visibility: c.visibility, input: c.input, expected: c.expected, weight: Number(c.weight) || 1, purpose: c.purpose })) : undefined,
    }
  }

  async function save() {
    setBusy("save")
    setError("")
    try {
      if (id === "new") { await post("/questions", payload()); toast.success("Question created") }
      else { await put(`/questions/${id}`, payload()); toast.success("Question saved") }
      navigate("/admin/questions")  // the bank shows the new or updated question at the top
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy("")
    }
  }

  async function generate() {
    setBusy("ai")
    try {
      const samples = [...f.cases.filter((c) => c.visibility === "open"), ...f.cases.filter((c) => c.visibility !== "open")]
      const out = await post("/questions/generate-cases", {
        count: 8, statement: toHtml(f.body), constraints: f.constraints, examples: samples.map((c) => c.input),
        reference: { language: f.ref_lang, source: f.ref_source }, time_limit_ms: Number(f.time_limit_ms), memory_mb: Number(f.memory_mb),
      })
      setCheck(null)
      set("cases", [...f.cases, ...out.cases.map((c) => ({ ...c, visibility: "hidden", weight: 1 }))])
      toast.success(`${out.cases.length} cases added as hidden${out.dropped ? ` (${out.dropped} dropped: the reference solution failed on them)` : ""}. Review them, then Save.`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy("")
    }
  }

  async function validate() {
    setBusy("check")
    try {
      const out = await post("/questions/check-reference", {
        reference: { language: f.ref_lang, source: f.ref_source }, time_limit_ms: Number(f.time_limit_ms), memory_mb: Number(f.memory_mb),
        cases: f.cases.map((c) => ({ visibility: c.visibility, input: c.input, expected: c.expected })),
      })
      setCheck(out.verdicts)
      out.passed === out.total ? toast.success(`Reference solution passes all ${out.total} cases`) : toast.error(`Reference solution passes ${out.passed} of ${out.total} cases. The failing ones are marked below.`)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy("")
    }
  }

  const ready = !!f.ref_source.trim() && f.cases.length > 0
  const toggleLang = (k) => set("languages", f.languages.includes(k) ? f.languages.filter((x) => x !== k) : [...f.languages, k])

  return (
    <div className="grid max-w-4xl gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{id === "new" ? "New question" : "Edit question"}</h1>
        <Button variant="ghost" asChild><Link to="/admin/questions">Back to bank</Link></Button>
      </div>

      <Card>
        <CardContent className="grid gap-4 pt-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2">
              <Label>Type</Label>
              <Select value={f.type} onValueChange={pickType} disabled={id !== "new"}>
                <SelectTrigger aria-label="Question type"><SelectValue /></SelectTrigger>
                <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{TYPE_LABEL[t]}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Difficulty</Label>
              <Select value={f.difficulty} onValueChange={(v) => set("difficulty", v)}>
                <SelectTrigger aria-label="Difficulty"><SelectValue /></SelectTrigger>
                <SelectContent>{["easy", "medium", "hard"].map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="title">Title</Label>
            <Input id="title" value={f.title} onChange={(e) => set("title", e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="body">Question text</Label>
            <Textarea id="body" className="min-h-28" value={f.body} onChange={(e) => set("body", e.target.value)} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="grid gap-2"><Label htmlFor="marks">Marks</Label><Input id="marks" type="number" step="0.25" min="0.25" value={f.marks} onChange={(e) => set("marks", e.target.value)} /></div>
            {isMcq && <div className="grid gap-2"><Label htmlFor="neg">Negative marks (wrong answer)</Label><Input id="neg" type="number" step="0.25" min="0" value={f.negative_marks} onChange={(e) => set("negative_marks", e.target.value)} /></div>}
            <div className="grid gap-2"><Label htmlFor="skills">Skills (comma separated)</Label><Input id="skills" value={f.skills} onChange={(e) => set("skills", e.target.value)} /></div>
          </div>
        </CardContent>
      </Card>

      {isMcq && (
        <Card>
          <CardHeader><CardTitle>Options</CardTitle><CardDescription>{f.type === "mcq_single" ? "Choose the one correct answer." : "Tick every correct answer."} Use 2 to 8 options.</CardDescription></CardHeader>
          <CardContent className="grid gap-2">
            <RadioGroup value={f.options.find((o) => o.correct)?.id ?? ""} onValueChange={(v) => set("options", f.options.map((o) => ({ ...o, correct: o.id === v })))} className="gap-2">
              {f.options.map((o, i) => (
                <div key={o.id} className="flex items-center gap-2">
                  {f.type === "mcq_single"
                    ? <RadioGroupItem value={o.id} aria-label={`Option ${i + 1} is correct`} />
                    : <Checkbox checked={o.correct} onCheckedChange={(v) => setOption(i, { correct: v === true })} aria-label={`Option ${i + 1} is correct`} />}
                  <Input aria-label={`Option ${i + 1}`} value={o.text} onChange={(e) => setOption(i, { text: e.target.value })} />
                  <Button variant="ghost" size="icon" aria-label={`Remove option ${i + 1}`} disabled={f.options.length <= 2} onClick={() => set("options", f.options.filter((_, j) => j !== i))}><Trash2 /></Button>
                </div>
              ))}
            </RadioGroup>
            <div><Button variant="outline" size="sm" disabled={f.options.length >= 8} onClick={() => set("options", [...f.options, { id: rid(), text: "", correct: false }])}><Plus /> Add option</Button></div>
          </CardContent>
        </Card>
      )}

      {isText && (
        <Card>
          <CardHeader><CardTitle>Model answer</CardTitle><CardDescription>The AI marks each written answer against this, and you can override the mark after the exam.</CardDescription></CardHeader>
          <CardContent className="grid gap-4">
            <Textarea aria-label="Model answer" className="min-h-28" value={f.model_answer} onChange={(e) => set("model_answer", e.target.value)} />
            <div className="grid gap-4 md:grid-cols-2">
              {f.type === "short" && (
                <div className="grid gap-2">
                  <Label htmlFor="kw">Keywords (comma separated, use | for synonyms)</Label>
                  <Input id="kw" placeholder="unique|uuid, retry|retries" value={f.keywords} onChange={(e) => set("keywords", e.target.value)} />
                </div>
              )}
              <div className="grid gap-2"><Label htmlFor="mw">Word limit</Label><Input id="mw" type="number" min="10" value={f.max_words} onChange={(e) => set("max_words", e.target.value)} /></div>
            </div>
          </CardContent>
        </Card>
      )}

      {f.type === "coding" && (
        <>
          <Card>
            <CardHeader><CardTitle>Problem setup</CardTitle><CardDescription>Programs read standard input and print to standard output.</CardDescription></CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-2">
                <Label>Allowed languages</Label>
                <div className="flex flex-wrap gap-4">
                  {LANGS.map(([k, name]) => (
                    <Label key={k} className="flex items-center gap-2 font-normal"><Checkbox checked={f.languages.includes(k)} onCheckedChange={() => toggleLang(k)} /> {name}</Label>
                  ))}
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="grid gap-2"><Label htmlFor="tl">Time limit per case (ms)</Label><Input id="tl" type="number" min="100" max="10000" value={f.time_limit_ms} onChange={(e) => set("time_limit_ms", e.target.value)} /></div>
                <div className="grid gap-2"><Label htmlFor="ml">Memory limit (MB)</Label><Input id="ml" type="number" min="32" max="1024" value={f.memory_mb} onChange={(e) => set("memory_mb", e.target.value)} /></div>
              </div>
              <div className="grid gap-2"><Label htmlFor="cons">Constraints (the AI reads these when it makes test cases)</Label><Textarea id="cons" value={f.constraints} onChange={(e) => set("constraints", e.target.value)} /></div>
              <div className="grid gap-2">
                <Label>Reference solution</Label>
                <Select value={f.ref_lang} onValueChange={(v) => set("ref_lang", v)}>
                  <SelectTrigger className="w-48" aria-label="Reference language"><SelectValue /></SelectTrigger>
                  <SelectContent>{LANGS.map(([k, name]) => <SelectItem key={k} value={k}>{name}</SelectItem>)}</SelectContent>
                </Select>
                <Textarea aria-label="Reference solution" className="min-h-40 font-mono text-xs" value={f.ref_source} onChange={(e) => set("ref_source", e.target.value)} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Test cases</CardTitle>
              <CardDescription>Sample cases are shown to the candidate (use 1 or 2). Hidden cases decide the marks. Weights are relative; marks are split in proportion.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => set("cases", [...f.cases, { input: "", expected: "", visibility: f.cases.length ? "hidden" : "open", weight: 1, purpose: "" }])}><Plus /> Add case</Button>
                <Button variant="outline" size="sm" disabled={!ready || busy === "ai"} onClick={generate}><Sparkles /> {busy === "ai" ? "Generating..." : "Generate with AI"}</Button>
                <Button variant="outline" size="sm" disabled={!ready || busy === "check"} onClick={validate}>Check reference solution</Button>
              </div>
              {!ready && <p className="text-xs text-muted-foreground">Add a reference solution and at least one sample case to use the AI helper and the check.</p>}
              {f.cases.map((c, i) => (
                <div key={i} className="grid gap-2 rounded-lg border p-3" data-testid="case-row">
                  <div className="flex items-center gap-2">
                    <Select value={c.visibility} onValueChange={(v) => setCase(i, { visibility: v })}>
                      <SelectTrigger className="w-36" aria-label={`Case ${i + 1} visibility`}><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="open">Sample (visible)</SelectItem><SelectItem value="hidden">Hidden</SelectItem></SelectContent>
                    </Select>
                    {check?.[i] && <Verdict v={check[i]} />}
                    <Input className="w-24" type="number" step="0.5" min="0.5" aria-label={`Case ${i + 1} weight`} value={c.weight} onChange={(e) => setCase(i, { weight: e.target.value })} />
                    <Input aria-label={`Case ${i + 1} note`} placeholder="Note (what it tests)" value={c.purpose} onChange={(e) => setCase(i, { purpose: e.target.value })} />
                    <Button variant="ghost" size="icon" aria-label={`Remove case ${i + 1}`} onClick={() => { setCheck(null); set("cases", f.cases.filter((_, j) => j !== i)) }}><Trash2 /></Button>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <Textarea aria-label={`Case ${i + 1} input`} placeholder="Input" className="min-h-16 font-mono text-xs" value={c.input} onChange={(e) => setCase(i, { input: e.target.value })} />
                    <Textarea aria-label={`Case ${i + 1} expected output`} placeholder="Expected output" className="min-h-16 font-mono text-xs" value={c.expected} onChange={(e) => setCase(i, { expected: e.target.value })} />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}

      {f.type === "sql" && <SqlBuilder f={f} set={set} />}

      {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
      <div><Button onClick={save} disabled={busy === "save"}>{busy === "save" ? "Saving..." : "Save question"}</Button></div>
    </div>
  )
}
