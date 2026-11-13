import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"
import { ArrowLeft, Download } from "lucide-react"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { saveFile } from "@/lib/download"
import { TONE } from "@/lib/verdict"
import Brand from "@/components/Brand"
import SignOutButton from "@/components/SignOutButton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const STATUS_TONE = { Correct: "good", Incorrect: "bad", "Partly correct": "part", "Not answered": "none", "Awaiting marking": "info" }
const RING = { passed: "#16a34a", not_passed: "#dc2626", not_attempted: "#d97706" }

function Ring({ percent, result }) {
  const r = 52, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, percent))
  return (
    <svg viewBox="0 0 128 128" className="size-32 shrink-0" role="img" aria-label={`${percent} percent`}>
      <circle cx="64" cy="64" r={r} fill="none" stroke="#e2e8f0" strokeWidth="11" />
      {p > 0 && <circle cx="64" cy="64" r={r} fill="none" stroke={RING[result] ?? "#1d4ed8"} strokeWidth="11" strokeLinecap="round" strokeDasharray={`${(c * p) / 100} ${c}`} transform="rotate(-90 64 64)" />}
      <text x="64" y="68" textAnchor="middle" className="fill-slate-900 text-[26px] font-semibold" style={{ fontFamily: "Poppins, sans-serif" }}>{percent}%</text>
    </svg>
  )
}

function Bar({ label, score, max, average }) {
  const w = (v) => `${Math.max(0, Math.min(100, max ? (100 * v) / max : 0))}%`
  return (
    <div className="grid gap-1" data-testid="rc-bar">
      <div className="flex items-baseline justify-between gap-2 text-sm"><span className="font-medium">{label}</span><span className="font-semibold">{score} / {max}</span></div>
      <div className="relative h-2.5 rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-primary" style={{ width: w(score) }} />
        {average != null && <div className="absolute -top-1 h-4.5 w-0.5 bg-slate-900" style={{ left: w(average), height: 18 }} title={`Class average ${average}`} />}
      </div>
      {average != null && <span className="text-right text-xs text-muted-foreground">class average {average}</span>}
    </div>
  )
}

export default function ReportCard() {
  const { attemptId } = useParams()
  const { user } = useAuth()
  const [d, setD] = useState(null)
  const [error, setError] = useState("")
  useEffect(() => { get(`/attempts/${attemptId}/report-card`).then(setD).catch((e) => setError(e.message)) }, [attemptId])

  const download = () => saveFile(`/attempts/${attemptId}/report-card.pdf`, "report-card.pdf").catch((e) => toast.error(e.message))
  const tiles = d && [["Rank", d.rank ? `${d.rank} of ${d.of}` : "-"], ["Class average", `${d.class_average}%`], ["Highest score", `${d.highest}%`],
    ["Time taken", d.exam.minutes_taken != null ? `${d.exam.minutes_taken} min` : "-", `of ${d.exam.minutes_allowed} min`], ["Attempted", `${d.attempted} of ${d.questions}`, "questions"]]

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="flex items-center justify-between border-b bg-white px-6 py-3">
        <Brand />
        <div className="flex items-center gap-3 text-sm"><span>{user.name || user.email}</span><SignOutButton /></div>
      </header>
      <main className="mx-auto grid max-w-4xl gap-4 p-4 sm:p-6" data-testid="report-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" asChild><Link to="/exam"><ArrowLeft /> Your exams</Link></Button>
          {d && <Button onClick={download}><Download /> Download PDF</Button>}
        </div>
        {error && <p className="rounded-lg border bg-white p-4 text-sm text-destructive" role="alert">{error}</p>}
        {!d && !error && <p className="text-muted-foreground">Loading...</p>}
        {d && (
          <>
            <section className="flex flex-wrap items-center justify-between gap-6 rounded-2xl border bg-white p-6 shadow-sm">
              <div className="grid min-w-0 flex-1 gap-3">
                <div>
                  <p className="text-xs font-semibold tracking-wide text-muted-foreground">ASSESSMENT REPORT CARD</p>
                  <h1 className="break-words text-2xl font-semibold" data-testid="rc-name">{d.candidate.name}</h1>
                  <p className="text-sm text-muted-foreground">{[d.candidate.login && `Login: ${d.candidate.login}`, d.candidate.email].filter(Boolean).join(" · ")}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold tracking-wide text-muted-foreground">EXAM</p>
                  <p className="break-words text-lg font-semibold text-primary" data-testid="rc-exam">{d.exam.title}</p>
                  <p className="text-sm text-muted-foreground">{[d.exam.department, d.exam.taken_at].filter(Boolean).join(" · ")}</p>
                </div>
              </div>
              <div className="grid justify-items-center gap-2">
                <Ring percent={d.score.percent} result={d.score.result} />
                <span className="text-sm text-muted-foreground" data-testid="rc-score">{d.score.score} / {d.score.max}</span>
                {d.score.result !== "no_pass_mark" && <Badge variant="outline" className={TONE[{ passed: "good", not_passed: "bad", not_attempted: "part" }[d.score.result]]} data-testid="rc-result">{d.score.result_label}</Badge>}
              </div>
            </section>
            {!d.declared && <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">Preview: the results have not been declared yet.</p>}
            {d.note && <p className="text-sm text-amber-700">{d.note}</p>}

            <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {tiles.map(([label, value, sub]) => (
                <div key={label} className="rounded-xl border bg-white p-3 shadow-sm">
                  <p className="text-[11px] font-semibold tracking-wide text-muted-foreground">{label.toUpperCase()}</p>
                  <p className="text-lg font-semibold">{value}</p>
                  {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
                </div>
              ))}
            </section>

            {d.sections.some((s) => s.max) && (
              <section className="grid gap-4 rounded-2xl border bg-white p-6 shadow-sm">
                <h2 className="font-semibold">Performance by section</h2>
                {d.sections.filter((s) => s.max).map((s) => <Bar key={s.title} label={s.title} score={s.score} max={s.max} average={s.average} />)}
                <p className="text-xs text-muted-foreground">The dark mark on each bar is the class average.</p>
                {d.kinds.length > 0 && <><h2 className="mt-2 font-semibold">By type of question</h2>{d.kinds.filter((k) => k.max).map((k) => <Bar key={k.kind} label={k.kind} score={k.score} max={k.max} />)}</>}
                {d.highlights.length > 0 && <ul className="list-disc pl-5 text-sm">{d.highlights.map((h) => <li key={h}>{h}</li>)}</ul>}
              </section>
            )}

            <section className="grid gap-4 rounded-2xl border bg-white p-6 shadow-sm">
              <h2 className="font-semibold">Question-wise result</h2>
              {d.sections.filter((s) => s.questions.length).map((s) => (
                <div key={s.title} className="grid gap-1" data-testid="rc-section">
                  <div className="flex items-center justify-between rounded-lg bg-primary/10 px-3 py-2 text-sm font-semibold"><span>{s.title}</span><span>{s.score} / {s.max}</span></div>
                  {s.questions.map((q) => (
                    <div key={q.n} className="grid grid-cols-[2rem_1fr_auto] items-center gap-x-3 gap-y-1 border-b px-2 py-2 text-sm sm:grid-cols-[2rem_1fr_5rem_6rem_8rem]" data-testid="rc-question">
                      <span className="text-muted-foreground">{q.n}</span>
                      <span className="min-w-0 break-words">{q.title}</span>
                      <span className="hidden text-muted-foreground sm:block">{q.kind}</span>
                      <span className="hidden sm:block">{q.score} / {q.marks}</span>
                      <Badge variant="outline" className={`justify-self-end ${TONE[STATUS_TONE[q.status] ?? "none"]}`}>{q.status}</Badge>
                    </div>
                  ))}
                </div>
              ))}
            </section>
            <p className="text-center text-xs text-muted-foreground">Report no. {d.report_no} · {d.generated_at} · Marks may be revised by the examiner.</p>
          </>
        )}
      </main>
    </div>
  )
}
