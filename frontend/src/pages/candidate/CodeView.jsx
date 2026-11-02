import { useState } from "react"
import CodeMirror from "@uiw/react-codemirror"
import { EditorView } from "@codemirror/view"
import { python } from "@codemirror/lang-python"
import { java } from "@codemirror/lang-java"
import { javascript } from "@codemirror/lang-javascript"
import { cpp } from "@codemirror/lang-cpp"
import { sql } from "@codemirror/lang-sql"
import { Loader2 } from "lucide-react"
import { get, post } from "@/lib/api"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

// Words the candidate sees for each judge verdict code.
const VERDICT = {
  AC: "Success", WA: "Failed", TLE: "Time Limit Exceeded", MLE: "Memory Limit Exceeded",
  RE: "Runtime Error", CE: "Compilation Error", OLE: "Output Limit Exceeded", IE: "Judge Error",
}

export function Verdict({ v }) {
  return <Badge className={v === "AC" ? "bg-green-600 text-white" : "bg-destructive text-white"}>{VERDICT[v] ?? v}</Badge>
}

// A query result or a table of sample data: {columns, rows}.
export function DataTable({ data }) {
  if (!data?.columns) return <p className="text-xs text-muted-foreground">-</p>
  return (
    <div className="max-h-48 overflow-auto rounded-md border">
      <Table>
        <TableHeader><TableRow>{data.columns.map((c) => <TableHead key={c} className="h-8 text-xs">{c}</TableHead>)}</TableRow></TableHeader>
        <TableBody>
          {data.rows.slice(0, 50).map((row, i) => (
            <TableRow key={i}>{row.map((v, j) => <TableCell key={j} className="py-1 text-xs">{v === null ? "NULL" : String(v)}</TableCell>)}</TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// SQL question: the schema, then for each sample the input tables and the expected output, formatted as tables.
export function SqlSamples({ q }) {
  return (
    <div className="grid gap-4">
      <details>
        <summary className="cursor-pointer text-sm font-medium">Schema</summary>
        <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">{q.schema}</pre>
      </details>
      {q.open_cases.map((c) => (
        <div key={c.ordinal} className="grid gap-2">
          <b className="text-sm">Sample {c.ordinal}</b>
          <div className="text-xs text-muted-foreground">Input tables</div>
          {c.tables.map((t) => (
            <div key={t.name} className="grid gap-1"><span className="text-xs font-medium">{t.name}</span><DataTable data={t} /></div>
          ))}
          <div className="text-xs text-muted-foreground">Expected output</div>
          <DataTable data={c.expected} />
        </div>
      ))}
      <p className="text-xs text-muted-foreground">{q.ordered ? "Row order matters." : "Row order does not matter."} Column names are checked.</p>
    </div>
  )
}

const EXT = { python, java, javascript, c: cpp, cpp, sql }

// One placeholder row per test case while the judge works.
function Running({ samples, privateCases }) {
  const labels = [
    ...Array.from({ length: samples }, (_, i) => `Sample ${i + 1}`),
    ...Array.from({ length: privateCases }, (_, i) => `Private test case ${i + 1}`),
  ]
  return labels.map((label) => (
    <div key={label} className="flex items-center gap-2 rounded-md border p-2" data-testid="case-running">
      <span>{label}</span><Loader2 className="size-4 animate-spin text-primary" /><span className="text-xs text-muted-foreground">Running...</span>
    </div>
  ))
}

// Coding and SQL questions: editor, Run on the sample cases, Submit against every case.
export function CodeView({ q, r, onChange, attemptId, closed, blockPaste }) {
  const isSql = q.type === "sql"
  const langs = isSql ? q.engines : q.languages
  const lang = langs.some((l) => l.key === r.language) ? r.language : langs[0]?.key
  const blank = (k) => q.starter?.[k] ?? (isSql ? "-- Write one SQL query\n" : "")
  const [sources, setSources] = useState({ [lang]: r.source ?? blank(lang) })
  const [custom, setCustom] = useState(isSql ? "" : q.open_cases[0]?.input ?? "")
  const [busy, setBusy] = useState("")
  const [res, setRes] = useState(null)
  const src = sources[lang] ?? blank(lang)

  const setSrc = (v) => { setSources((s) => ({ ...s, [lang]: v })); onChange({ language: lang, source: v }) }
  const pickLang = (k) => onChange({ language: k, source: sources[k] ?? blank(k) }, true)

  async function exec(kind) {
    setBusy(kind)
    setRes(null)
    try {
      const out = await post(`/attempts/${attemptId}/code/${q.id}/${kind}`, {
        language: lang, source: src, custom_input: kind === "run" && !isSql && custom.trim() ? custom : undefined,
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
    EXT[lang]?.() ?? [],
    EditorView.lineWrapping,
    ...(blockPaste ? [EditorView.domEventHandlers({ paste: (e) => { e.preventDefault(); return true }, drop: (e) => { e.preventDefault(); return true } })] : []),
  ]
  const result = res?.result
  const privateRows = result?.hidden?.cases ?? []

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={lang} onValueChange={pickLang} disabled={closed}>
          <SelectTrigger className="w-52" aria-label={isSql ? "SQL engine" : "Language"}><SelectValue /></SelectTrigger>
          <SelectContent>{langs.map((l) => <SelectItem key={l.key} value={l.key}>{l.name}</SelectItem>)}</SelectContent>
        </Select>
        {!isSql && <span className="text-xs text-muted-foreground">Time limit {q.time_limit_ms / 1000}s per case, memory {q.memory_mb} MB</span>}
      </div>
      {!langs.length && <Alert variant="destructive" className="p-3">Nothing is installed on the server to run this question. Tell the invigilator.</Alert>}
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
          {!isSql && <TabsTrigger value="input">Custom input</TabsTrigger>}
        </TabsList>
        {!isSql && (
          <TabsContent value="input" className="grid gap-2">
            <Label htmlFor={`custom-${q.id}`} className="text-xs text-muted-foreground">Input for "Run on samples" (optional)</Label>
            <Textarea id={`custom-${q.id}`} className="font-mono text-xs" value={custom} onChange={(e) => setCustom(e.target.value)} />
            {result?.custom && <pre className="whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">{result.custom.verdict}: {result.custom.stdout}{result.custom.stderr}</pre>}
          </TabsContent>
        )}
        <TabsContent value="results" className="grid gap-2 text-sm" data-testid="code-results">
          {busy && <Running samples={q.open_cases.length} privateCases={busy === "submit" ? q.hidden_weights.length : 0} />}
          {!busy && !res && <p className="text-muted-foreground">Run checks the sample cases. Submit also checks the private test cases and is what counts.</p>}
          {!busy && res?.status === "error" && <Alert variant="destructive" className="p-3">{result?.error}</Alert>}
          {!busy && result?.compile && !result.compile.ok && <Alert variant="destructive" className="p-3"><pre className="whitespace-pre-wrap text-xs">{result.compile.message}</pre></Alert>}
          {!busy && result?.open?.map((c) => (
            <details key={c.ordinal} className="rounded-md border p-2">
              <summary className="flex cursor-pointer items-center gap-2">
                Sample {c.ordinal} <Verdict v={c.verdict} /><span className="text-xs text-muted-foreground">{c.time_ms ?? 0} ms</span>
              </summary>
              {isSql ? (
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <div className="grid gap-1"><span className="text-xs text-muted-foreground">Your output</span><DataTable data={c.result} /></div>
                  <div className="grid gap-1"><span className="text-xs text-muted-foreground">Expected output</span><DataTable data={c.expected_result} /></div>
                </div>
              ) : (
                <div className="mt-2 grid gap-2 text-xs md:grid-cols-3">
                  {[["Input", c.input], ["Expected", c.expected], ["Your output", c.stdout]].map(([label, v]) => (
                    <div key={label}><div className="text-muted-foreground">{label}</div><pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted p-1.5">{(v ?? "").slice(0, 1500)}</pre></div>
                  ))}
                </div>
              )}
              {c.stderr && <pre className="mt-2 whitespace-pre-wrap text-xs text-destructive">{c.stderr}</pre>}
            </details>
          ))}
          {!busy && privateRows.map((c, i) => (
            <div key={c.ordinal} className="flex items-center gap-2 rounded-md border p-2" data-testid="private-case">
              Private test case {i + 1} <Verdict v={c.verdict} /><span className="text-xs text-muted-foreground">{c.time_ms ?? 0} ms</span>
            </div>
          ))}
          {!busy && res?.status === "done" && (
            <p className="font-medium">
              {result.passed} / {result.total} test cases passed{res.kind === "submit" ? `. Score ${result.score} / ${result.max_score}` : ". Private test cases run when you press Submit."}
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
