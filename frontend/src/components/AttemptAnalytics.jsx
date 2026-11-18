import { useEffect, useState } from "react"
import { get } from "@/lib/api"
import { QUESTION_TONE, RESULT, TONE } from "@/lib/verdict"
import { Badge } from "@/components/ui/badge"
import { Bar, COLOR, Histogram, Legend, Panel, Ring, Tile } from "@/components/charts"
import { Loading } from "@/components/Spinner"

const GROUPS = [["kinds", "By type of question"], ["difficulty", "By difficulty"], ["skills", "By topic"]]
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1)

// One candidate against the class. Used on the candidate's own page and on the reviewer's page, so both read the same numbers.
export default function AttemptAnalytics({ attemptId }) {
  const [d, setD] = useState(null)
  const [error, setError] = useState("")
  useEffect(() => { setD(null); setError(""); get(`/attempts/${attemptId}/analytics`).then(setD).catch((e) => setError(e.message)) }, [attemptId])

  if (error) return <p className="rounded-lg border bg-white p-4 text-sm text-destructive" role="alert">{error}</p>
  if (!d) return <Loading />
  const s = d.score, c = d.class
  const [label, tone] = RESULT[s.result]
  const time = d.time.taken != null ? `${d.time.taken} min` : "-"
  return (
    <div className="grid gap-4" data-testid="attempt-analytics">
      <section className="flex flex-wrap items-center justify-between gap-6 rounded-2xl border bg-white p-6 shadow-sm">
        <div className="grid min-w-0 flex-1 gap-2">
          <p className="text-xs font-semibold tracking-wide text-muted-foreground">ANALYTICS</p>
          <h1 className="break-words text-2xl font-semibold" data-testid="aa-name">{d.candidate.name}</h1>
          <p className="break-words text-lg font-semibold text-primary">{d.exam.title}</p>
          <p className="text-sm" data-testid="aa-standing">
            {d.rank ? <>Rank <b>{d.rank}</b> of <b>{d.of}</b>. </> : null}
            {d.beat_percent != null ? <>You scored higher than <b>{d.beat_percent}%</b> of the other candidates.</> : "You were the only candidate who finished, so there is nothing to compare with yet."}
          </p>
          {!d.exam.declared && <p className="text-sm text-amber-700">Preview: the results have not been declared yet.</p>}
        </div>
        <div className="grid justify-items-center gap-2">
          <Ring percent={s.percent} result={s.result} />
          <span className="text-sm text-muted-foreground">{s.score} / {s.max}</span>
          {s.result !== "no_pass_mark" && <Badge variant="outline" className={TONE[tone]}>{label}</Badge>}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Tile label="Your score" value={`${s.percent}%`} />
        <Tile label="Class average" value={`${c.mean}%`} sub={`of ${c.n} candidate${c.n === 1 ? "" : "s"}`} />
        <Tile label="Class median" value={`${c.median}%`} />
        <Tile label="Highest score" value={`${c.highest}%`} />
        <Tile label="Time taken" value={time} sub={d.time.class_average != null ? `class average ${d.time.class_average} min of ${d.time.allowed}` : `of ${d.time.allowed} min`} />
      </section>

      <Panel title="Where you stand in the class" hint="Each bar is a band of 10 percentage points. The number on top is how many candidates scored in it.">
        <Histogram bins={d.histogram} you={d.you_bin} marks={[{ at: c.mean, label: `Class average ${c.mean}%`, color: COLOR.slate }, { at: s.percent, label: "You", color: COLOR.green }]} data-testid="aa-histogram" />
        <Legend items={[[COLOR.green, "The band you are in"], [COLOR.blue, "Other bands"]]} />
      </Panel>

      {d.sections.length > 0 && (
        <Panel title="Sections: you and the class" hint="The dark mark on each bar is the class average." data-testid="aa-sections">
          {d.sections.map((x) => <Bar key={x.title} label={x.title} score={x.you} max={100} average={x.class} text={`${x.score} / ${x.max} (${x.you}%)`} averageText={`class average ${x.class}% · best ${x.best}%`} />)}
          {d.highlights.length > 0 && <ul className="list-disc pl-5 text-sm">{d.highlights.map((h) => <li key={h}>{h}</li>)}</ul>}
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {GROUPS.filter(([k]) => d[k].length > 0).map(([k, title]) => (
          <Panel key={k} title={title} data-testid={`aa-${k}`}>
            {d[k].map((x) => <Bar key={x.name} label={`${cap(x.name)} (${x.n})`} score={x.you} max={100} average={x.class} text={`${x.you}%`} averageText={`class average ${x.class}%`} />)}
          </Panel>
        ))}
      </div>

      <Panel title="Question by question" hint="On a wider screen the last column shows how much of the class got that question completely right.">
        {d.questions.map((q) => (
          <div key={q.n} className="grid grid-cols-[2rem_1fr_auto] items-center gap-x-3 gap-y-1 border-b px-2 py-2 text-sm sm:grid-cols-[2rem_1fr_5rem_6rem_8rem_5rem]" data-testid="aa-question">
            <span className="text-muted-foreground">{q.n}</span>
            <span className="min-w-0 break-words">{q.title}</span>
            <span className="hidden text-muted-foreground sm:block">{q.kind}</span>
            <span className="hidden sm:block">{q.score} / {q.marks}</span>
            <Badge variant="outline" className={`justify-self-end ${TONE[QUESTION_TONE[q.status] ?? "none"]}`}>{q.status}</Badge>
            <span className="hidden text-right text-muted-foreground sm:block" title="Share of the class that got it completely right">{q.class_correct != null ? `${q.class_correct}%` : "-"}</span>
          </div>
        ))}
      </Panel>
    </div>
  )
}
