import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft, BarChart3 } from "lucide-react"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { QUESTION_TONE, TONE } from "@/lib/verdict"
import Brand from "@/components/Brand"
import PdfButton from "@/components/PdfButton"
import SignOutButton from "@/components/SignOutButton"
import { Bar, Ring } from "@/components/charts"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Loading } from "@/components/Spinner"

export default function ReportCard() {
  const { attemptId } = useParams()
  const { user } = useAuth()
  const [d, setD] = useState(null)
  const [error, setError] = useState("")
  useEffect(() => { get(`/attempts/${attemptId}/report-card`).then(setD).catch((e) => setError(e.message)) }, [attemptId])

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
          {d && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" asChild><Link to={`/exam/analytics/${attemptId}`}><BarChart3 /> View analytics</Link></Button>
              <PdfButton path={`/attempts/${attemptId}/report-card.pdf`} label="Report card PDF" description={d.exam.title} />
            </div>
          )}
        </div>
        {error && <p className="rounded-lg border bg-white p-4 text-sm text-destructive" role="alert">{error}</p>}
        {!d && !error && <Loading />}
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
                      <Badge variant="outline" className={`justify-self-end ${TONE[QUESTION_TONE[q.status] ?? "none"]}`}>{q.status}</Badge>
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
