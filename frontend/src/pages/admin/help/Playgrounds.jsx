import { useEffect, useState } from "react"
import { toast } from "sonner"
import CodeMirror from "@uiw/react-codemirror"
import { EditorView } from "@codemirror/view"
import { vscodeLight } from "@uiw/codemirror-theme-vscode"
import { Copy } from "lucide-react"
import { get, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useDepartments } from "@/lib/useDepartments"
import { DataTable, languageFor, Verdict } from "@/pages/candidate/CodeView"
import { PackReport, parsePack } from "@/pages/admin/QuestionPack"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

// ---- the samples come from the server (the same valid questions the AI prompt shows), so the Help can never show a format the server refuses
let cached
export function useSamples() {
  const [samples, setSamples] = useState(null)
  const [error, setError] = useState("")
  useEffect(() => {
    (cached ??= get("/help/samples")).then(setSamples).catch((e) => { cached = null; setError(e.message) })
  }, [])
  return [samples, error]
}

export function Sample({ text }) {
  async function copy() {
    try { await navigator.clipboard.writeText(text); toast.success("Copied") } catch { toast.error("The browser blocked copying. Select the text and copy it.") }
  }
  return (
    <div className="relative min-w-0">
      <pre className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 pr-20 text-xs" data-testid="sample">{text}</pre>
      <Button type="button" variant="outline" size="xs" className="absolute right-2 top-2" onClick={copy}><Copy /> Copy</Button>
    </div>
  )
}

// One valid question of a type, as the server's own sample.
export function SampleOf({ type }) {
  const [samples, error] = useSamples()
  if (error) return <p className="text-sm text-destructive">The sample could not be loaded: {error}</p>
  if (!samples) return <p className="text-sm text-muted-foreground">Loading the sample...</p>
  return <Sample text={JSON.stringify(samples.examples[type], null, 2)} />
}

// The whole valid file: one question of every type.
export function SamplePack() {
  const [samples, error] = useSamples()
  if (error) return <p className="text-sm text-destructive">The sample could not be loaded: {error}</p>
  return samples ? <Sample text={JSON.stringify(samples.pack, null, 2)} /> : <p className="text-sm text-muted-foreground">Loading the sample...</p>
}

// The playgrounds that run code or check files need the permission to author questions (the server would refuse the others).
function AuthorOnly({ children }) {
  const { user } = useAuth()
  return user.can.author ? children : <Alert className="p-3">This playground runs code on the server, so it is open to Test Creators and Org Admins. Ask one of them to try it, or read the topics above.</Alert>
}

const Box = ({ children, className = "" }) => <div className={"grid min-w-0 gap-3 rounded-lg border bg-card p-4 " + className}>{children}</div>
const Editor = ({ value, onChange, lang, isSql, label }) => (
  <div className="overflow-hidden rounded-md border" aria-label={label} data-testid="playground-editor">
    <CodeMirror value={value} height="220px" onChange={onChange} extensions={[languageFor(lang, isSql), EditorView.lineWrapping]} theme={vscodeLight} basicSetup={{ foldGutter: false }} />
  </div>
)

// ================================================================== 1. Check my JSON
export function TryJson() {
  const [samples] = useSamples()
  const { departments } = useDepartments()
  const [dept, setDept] = useState("")
  const [text, setText] = useState("")
  const [report, setReport] = useState(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const small = (s) => JSON.stringify({ ...s.pack, sections: s.pack.sections.filter((x) => ["mcq_single", "short"].includes(x.questions[0].type)) }, null, 2)
  useEffect(() => { if (samples && !text) setText(small(samples)) }, [samples])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (departments?.length && !dept) setDept(departments[0].id) }, [departments, dept])

  async function check() {
    setBusy(true); setError(""); setReport(null)
    try { setReport(await post("/help/check-pack", { pack: parsePack(text), department_id: dept })) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <AuthorOnly>
      <Box>
        <p className="text-sm">Edit the file below (try a wrong answer letter, a missing statement, or a coding question without a reference solution), then press Check. You see exactly what the real import would say. <b>Nothing is saved.</b></p>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={dept} onValueChange={setDept}>
            <SelectTrigger className="w-56" aria-label="Department for the check"><SelectValue placeholder="Department" /></SelectTrigger>
            <SelectContent>{(departments ?? []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="outline" size="sm" disabled={!samples} onClick={() => { setText(small(samples)); setReport(null); setError("") }}>Sample: one MCQ and one short answer</Button>
          <Button variant="outline" size="sm" disabled={!samples} onClick={() => { setText(JSON.stringify(samples.pack, null, 2)); setReport(null); setError("") }}>Sample: every type</Button>
        </div>
        <Textarea aria-label="JSON to check" className="h-64 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
        <div><Button disabled={busy || !dept || !text.trim()} onClick={check}>{busy ? "Checking..." : "Check (nothing is saved)"}</Button></div>
        {error && <Alert variant="destructive" className="p-3" data-testid="try-json-error">{error}</Alert>}
        <PackReport report={report} trial />
      </Box>
    </AuthorOnly>
  )
}

// ================================================================== 2. Try the exam screen
const SAMPLE_EXAM = [
  { type: "single", marks: 1, title: "Which of these numbers is prime?", options: ["4", "6", "7", "9"], correct: ["c"] },
  { type: "multi", marks: 2, title: "Which of these numbers are even? Choose all that apply.", options: ["2", "3", "4", "5"], correct: ["a", "c"] },
  { type: "short", marks: 2, title: "In one sentence, what is a primary key?" },
]

export function TryExam() {
  const [qi, setQi] = useState(0)
  const [ans, setAns] = useState({})  // question number -> chosen option letters, or the typed text
  const [marked, setMarked] = useState([])
  const [sheet, setSheet] = useState(null)
  const [busy, setBusy] = useState(false)
  const q = SAMPLE_EXAM[qi]
  const letter = (i) => String.fromCharCode(97 + i)
  const chosen = ans[qi] ?? (q.type === "short" ? "" : [])
  const answered = (i) => (SAMPLE_EXAM[i].type === "short" ? !!ans[i]?.trim() : !!ans[i]?.length)
  const pick = (id) => setAns({ ...ans, [qi]: q.type === "single" ? [id] : chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id] })
  const last = qi === SAMPLE_EXAM.length - 1

  async function finish() {
    setBusy(true)
    try {
      const rows = await Promise.all(SAMPLE_EXAM.map(async (s, i) => {
        if (s.type === "short") return { s, got: null }
        const r = await post("/help/try-mcq", { options: s.options.map((_, k) => letter(k)), correct: s.correct, selected: ans[i] ?? [], marks: s.marks, multi: s.type === "multi" })
        return { s, got: r.score }
      }))
      setSheet(rows)
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const restart = () => { setSheet(null); setAns({}); setMarked([]); setQi(0) }
  const said = (s, i) => (ans[i]?.length ? ans[i].map((x) => s.options[x.charCodeAt(0) - 97]).join(", ") : "nothing ticked")

  if (sheet) {
    const total = sheet.reduce((n, r) => n + (r.got ?? 0), 0)
    return (
      <Box>
        <h4 className="font-medium">Your marks (what the candidate's result sheet is built from)</h4>
        <div className="grid gap-2" data-testid="exam-sheet">
          {sheet.map(({ s, got }, i) => (
            <div key={i} className="rounded-md border p-2 text-sm">
              <p className="font-medium">{i + 1}. {s.title}</p>
              {got === null
                ? <p className="text-muted-foreground">You wrote: "{ans[i] || "nothing"}". A written answer is marked by AI and then checked by a person, so it has no mark here.</p>
                : <p>You chose: {said(s, i)}. Right: {s.correct.map((c) => s.options[c.charCodeAt(0) - 97]).join(", ")}. <b data-testid={`mark-${i + 1}`}>Marks: {got} of {s.marks}</b></p>}
            </div>
          ))}
          <p className="text-sm font-medium">Marked automatically: <span data-testid="exam-total">{total}</span> of {SAMPLE_EXAM.filter((s) => s.type !== "short").reduce((n, s) => n + s.marks, 0)}</p>
        </div>
        <p className="text-xs text-muted-foreground">Try question 2 again: tick every option (it scores 0), or tick both even numbers plus one odd one (a wrong tick takes 0.25 off).</p>
        <div><Button variant="outline" onClick={restart}>Try again</Button></div>
      </Box>
    )
  }
  return (
    <Box>
      <p className="text-sm">This is a made-up exam. It looks and behaves like the candidate's screen, but nothing is saved and no camera is used.</p>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sample question numbers">
        {SAMPLE_EXAM.map((_, i) => (
          <Button key={i} size="icon-sm" variant={i === qi ? "default" : answered(i) ? "secondary" : "outline"} aria-label={`Sample question ${i + 1}`}
            className={marked.includes(i) ? "ring-2 ring-destructive" : ""} onClick={() => setQi(i)}>{i + 1}</Button>
        ))}
        <span className="text-xs text-muted-foreground">Blue = answered, red outline = marked for review</span>
      </div>
      <div className="grid gap-3 rounded-lg border p-4" data-testid="exam-question">
        <h4 className="font-medium">{q.title} <span className="text-xs font-normal text-muted-foreground">({q.marks} {q.marks === 1 ? "mark" : "marks"})</span></h4>
        {q.type === "short"
          ? <Textarea aria-label="Your answer" className="h-24" value={chosen} onChange={(e) => setAns({ ...ans, [qi]: e.target.value })} />
          : q.options.map((o, i) => (
            <label key={i} className="flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm has-checked:border-primary has-checked:bg-primary/5">
              <input type={q.type === "single" ? "radio" : "checkbox"} name={`sample-${qi}`} className="size-4 accent-primary" checked={chosen.includes(letter(i))} onChange={() => pick(letter(i))} />
              {o}
            </label>
          ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={qi === 0} onClick={() => setQi(qi - 1)}>Previous</Button>
        <Button variant="outline" onClick={() => setMarked(marked.includes(qi) ? marked.filter((x) => x !== qi) : [...marked, qi])}>{marked.includes(qi) ? "Unmark review" : "Mark for review"}</Button>
        {last ? <Button className="ml-auto" disabled={busy} onClick={finish}>{busy ? "Marking..." : "Finish"}</Button> : <Button className="ml-auto" onClick={() => setQi(qi + 1)}>Save and next</Button>}
      </div>
    </Box>
  )
}

// ================================================================== 3. Try a coding question
const CASES = [
  { input: "2 3\n", expected: "5\n", visibility: "open" },
  { input: "-5 5\n", expected: "0\n", visibility: "open" },
  { input: "0 0\n", expected: "0\n", visibility: "hidden" },
  { input: "1000000000 1000000000\n", expected: "2000000000\n", visibility: "hidden" },
]

export function TryCoding() {
  const [samples] = useSamples()
  const [lang, setLang] = useState("python")
  const [codes, setCodes] = useState({})  // what was typed, per language
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const starters = samples?.examples.coding.starter ?? {}
  const src = codes[lang] ?? starters[lang] ?? ""
  const setSrc = (v) => { setCodes({ ...codes, [lang]: v }); setRes(null) }

  async function run() {
    setBusy(true); setRes(null)
    try { setRes(await post("/questions/check-reference", { reference: { language: lang, source: src }, cases: CASES, time_limit_ms: 2000, memory_mb: 256 })) } catch (e) { setRes({ error: e.message }) } finally { setBusy(false) }
  }
  return (
    <AuthorOnly>
      <Box>
        <div className="grid gap-1 text-sm">
          <p className="font-medium">Sum of two numbers</p>
          <p>Read two integers and print their sum. <b>Input:</b> one line, <code>a b</code>. <b>Output:</b> one line, <code>a + b</code>.</p>
          <p className="text-muted-foreground">Two sample cases are visible to the candidate (2 3 gives 5; -5 5 gives 0). Two more are hidden: the candidate only learns whether each passed.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={lang} onValueChange={(v) => { setLang(v); setRes(null) }}>
            <SelectTrigger className="w-44" aria-label="Language"><SelectValue /></SelectTrigger>
            <SelectContent>{Object.keys(starters).map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="outline" size="sm" disabled={!samples} onClick={() => { setLang("python"); setCodes({ ...codes, python: samples.examples.coding.reference.source }); setRes(null) }}>Show a correct solution (Python)</Button>
        </div>
        <Editor value={src} onChange={setSrc} lang={lang} label="Code editor" />
        <div><Button disabled={busy || !src.trim()} onClick={run}>{busy ? "Running..." : "Run on all cases"}</Button></div>
        {res?.error && <Alert variant="destructive" className="p-3" data-testid="try-code-error">{res.error}</Alert>}
        {res?.verdicts && (
          <div className="grid gap-2" data-testid="try-code-result">
            <p className="text-sm font-medium">{res.passed} of {res.total} test cases passed{res.message ? ". " + res.message : ""}</p>
            {CASES.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm" data-testid="try-code-case">
                <span className="w-32 font-medium">{c.visibility === "open" ? `Sample ${i + 1}` : `Hidden case ${i - 1}`}</span>
                {c.visibility === "open" && <span className="text-xs text-muted-foreground">input {c.input.trim()} , expected {c.expected.trim()}</span>}
                <span className="ml-auto"><Verdict v={res.verdicts[i]} /></span>
              </div>
            ))}
          </div>
        )}
      </Box>
    </AuthorOnly>
  )
}

// ================================================================== 4. Try an SQL question
const SQL_SCHEMA = "CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER);"
const SQL_DATA = "INSERT INTO employees VALUES (1,'Asha',60000),(2,'Ben',40000),(3,'Chen',55000),(4,'Dev',50000);"
const SQL_MODEL = "SELECT name FROM employees WHERE salary > 50000 ORDER BY name"
const TABLE = { columns: ["id", "name", "salary"], rows: [[1, "Asha", 60000], [2, "Ben", 40000], [3, "Chen", 55000], [4, "Dev", 50000]] }

export function TrySql() {
  const [query, setQuery] = useState("SELECT name FROM employees")
  const [out, setOut] = useState(null)  // { mine, expected }
  const [busy, setBusy] = useState(false)
  const preview = (reference_sql) => post("/questions/sql-preview", { ddl: SQL_SCHEMA, reference_sql, datasets: [SQL_DATA] }).then((r) => r.results[0])

  async function run() {
    setBusy(true); setOut(null)
    try {
      const [mine, expected] = await Promise.all([preview(query), preview(SQL_MODEL)])
      setOut({ mine, expected })
    } catch (e) { setOut({ error: e.message }) } finally { setBusy(false) }
  }
  const same = out?.mine?.ok && out.expected?.ok && JSON.stringify([out.mine.columns, out.mine.rows]) === JSON.stringify([out.expected.columns, out.expected.rows])
  return (
    <AuthorOnly>
      <Box>
        <div className="grid gap-2 text-sm">
          <p className="font-medium">Well paid employees</p>
          <p>Return the names of employees who earn <b>more than 50000</b>, in alphabetical order. Column: <code>name</code>.</p>
          <p className="text-xs text-muted-foreground">Table <code>employees</code> (this is the sample data the candidate sees). The result must match the expected output: column names and row order are checked.</p>
          <DataTable data={TABLE} />
        </div>
        <Editor value={query} onChange={(v) => { setQuery(v); setOut(null) }} isSql lang="sqlite" label="SQL editor" />
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy || !query.trim()} onClick={run}>{busy ? "Running..." : "Run"}</Button>
          <Button variant="outline" onClick={() => { setQuery(SQL_MODEL); setOut(null) }}>Show a correct query</Button>
        </div>
        {out?.error && <Alert variant="destructive" className="p-3" data-testid="try-sql-error">{out.error}</Alert>}
        {out?.mine && !out.mine.ok && <Alert variant="destructive" className="p-3" data-testid="try-sql-error">{out.mine.error}</Alert>}
        {out?.mine?.ok && (
          <div className="grid gap-2" data-testid="try-sql-result">
            <p className={"text-sm font-medium " + (same ? "text-green-700" : "text-destructive")}>{same ? "Matches the expected output" : "Does not match the expected output"}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1"><span className="text-xs font-medium">Your result</span><DataTable data={out.mine} /></div>
              <div className="grid gap-1"><span className="text-xs font-medium">Expected output</span><DataTable data={out.expected} /></div>
            </div>
          </div>
        )}
      </Box>
    </AuthorOnly>
  )
}
