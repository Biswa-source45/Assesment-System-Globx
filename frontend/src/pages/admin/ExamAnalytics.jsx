import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ChevronDown, ChevronRight } from "lucide-react"
import { get } from "@/lib/api"
import { RISK } from "@/lib/labels"
import { TONE } from "@/lib/verdict"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Bar, COLOR, Histogram, Legend, Panel, RISK_COLOR, Scatter, Tile } from "@/components/charts"
import { Loading } from "@/components/Spinner"

const HEALTH_TONE = { good: "good", "too easy": "part", "too hard": "part", "often skipped": "part", "check the key": "bad", "few answers": "none" }
const HEALTH_HELP = { "check the key": "The strongest candidates did worse on this question than the weakest. The answer key may be wrong.", "too easy": "Almost everyone got it right, so it tells you little.", "too hard": "Almost nobody got it right: check the question and the key.", "often skipped": "Many candidates left it blank.", "few answers": "Too few candidates for a verdict." }
const GROUPS = [["kinds", "By type of question"], ["difficulty", "By difficulty"], ["skills", "By topic (question tags)"]]
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1)
const pct = (v) => (v == null ? "-" : `${v}%`)

function Counts({ data, order, color }) {
  const keys = (order ?? Object.keys(data)).filter((k) => data[k] != null)
  const total = keys.reduce((a, k) => a + data[k], 0)
  return keys.map((k) => <Bar key={k} label={cap(RISK[k] ?? k.replace(/_/g, " "))} score={data[k]} max={total} text={`${data[k]}`} color={color?.[k]} />)
}

function QuestionRow({ q, n }) {
  const [open, setOpen] = useState(false)
  const total = q.options ? Math.max(1, q.attempts) : 1
  return (
    <div className="border-b" data-testid="aq-row" data-health={q.health}>
      <div className="grid grid-cols-[1.5rem_1fr_auto] items-center gap-x-3 gap-y-1 px-1 py-2 text-sm sm:grid-cols-[1.5rem_1fr_6rem_5rem_4.5rem_5rem_8rem]">
        {q.options ? <button type="button" className="text-muted-foreground" aria-label={open ? "Hide the options" : "Show how the options were chosen"} aria-expanded={open} onClick={() => setOpen(!open)}>{open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</button> : <span className="text-muted-foreground">{n}</span>}
        <span className="min-w-0 break-words">{q.title}<span className="ml-2 text-xs text-muted-foreground">{q.kind} · {q.difficulty} · {q.marks} mark{q.marks === 1 ? "" : "s"}</span></span>
        <span className="hidden sm:block"><span className="block h-2 rounded-full bg-slate-200"><span className="block h-full rounded-full bg-primary" style={{ width: `${Math.min(100, q.avg_percent)}%` }} /></span><span className="text-xs text-muted-foreground">{q.avg_percent}% earned</span></span>
        <span className="hidden text-right sm:block" title="Share who got full marks">{q.full_marks_pct}%</span>
        <span className="hidden text-right sm:block" title="Share who left it blank">{q.skipped_pct}%</span>
        <span className="hidden text-right sm:block" title="How well it separates strong from weak candidates (1 is best, below 0 is a warning)">{q.discrimination ?? "-"}</span>
        <Badge variant="outline" className={`justify-self-end ${TONE[HEALTH_TONE[q.health]]}`} title={HEALTH_HELP[q.health]}>{cap(q.health)}</Badge>
      </div>
      {open && q.options && (
        <div className="grid gap-1.5 px-8 pb-3" data-testid="aq-options">
          {q.options.map((o) => (
            <div key={o.label} className="grid grid-cols-[1.5rem_1fr_3rem] items-center gap-2 text-sm">
              <span className="font-semibold">{o.label}</span>
              <div className="grid gap-0.5">
                <span className="break-words">{o.text}{o.correct && <Badge variant="outline" className={`ml-2 ${TONE.good}`}>Right answer</Badge>}</span>
                <span className="block h-2 rounded-full bg-slate-200"><span className="block h-full rounded-full" style={{ width: `${(100 * o.chosen) / total}%`, background: o.correct ? COLOR.green : COLOR.slate }} /></span>
              </div>
              <span className="text-right">{o.chosen}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// The whole exam for a reviewer: who came, how they scored, how each section and question behaved, integrity and marking.
export default function ExamAnalytics({ testId }) {
  const [d, setD] = useState(null)
  const [problemsOnly, setProblemsOnly] = useState(false)
  useEffect(() => { setD(null); get(`/tests/${testId}/analytics`).then(setD).catch((e) => toast.error(e.message)) }, [testId])
  if (!d) return <Loading />

  const f = d.funnel, s = d.scores
  const none = f.completed === 0
  const marks = [s.mean != null && { at: s.mean, label: `Average ${s.mean}%`, color: COLOR.slate }, s.pass_mark_percent != null && { at: s.pass_mark_percent, label: `Pass mark ${s.pass_mark_percent}%`, color: COLOR.red }].filter(Boolean)
  const asked = problemsOnly ? d.questions.filter((q) => !["good", "few answers"].includes(q.health)) : d.questions
  const m = d.marking
  return (
    <div className="grid gap-4" data-testid="exam-analytics">
      {!d.calculated && !none && <Alert className="p-3" data-testid="aa-provisional">The results are not calculated yet, so these numbers can still change.</Alert>}
      {d.calculated && d.pending_review > 0 && <Alert className="p-3" data-testid="aa-provisional">{d.pending_review} candidate(s) are still waiting for review, so these numbers can still change.</Alert>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <Tile label="Finished" value={f.completed} sub={`of ${f.invited} invited`} data-testid="at-finished" />
        <Tile label="Average" value={pct(s.mean)} data-testid="at-mean" />
        <Tile label="Median" value={pct(s.median)} />
        <Tile label="Spread" value={s.std == null ? "-" : `±${s.std}`} sub="standard deviation" />
        <Tile label="Pass rate" value={pct(s.pass_rate)} sub={s.pass_rate == null ? "no pass mark" : undefined} />
        <Tile label="Highest" value={pct(s.max)} />
        <Tile label="Lowest" value={pct(s.min)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Who took the exam" data-testid="aa-funnel">
          <Bar label="Invited" score={f.invited} max={f.invited} text={`${f.invited}`} />
          <Bar label="Started" score={f.started} max={f.invited} text={`${f.started}`} />
          <Bar label="Finished" score={f.completed} max={f.invited} text={`${f.completed}`} />
          <Bar label="Passed" score={f.cleared_cutoff} max={f.invited} text={`${f.cleared_cutoff}`} color={COLOR.green} />
        </Panel>
        <Panel title="Score distribution" hint="How many candidates scored in each band of 10 percentage points.">
          <Histogram bins={d.score_distribution} marks={marks} data-testid="aa-score-hist" />
        </Panel>
      </div>

      {none ? <Panel><p className="text-sm text-muted-foreground" data-testid="aa-empty">No candidate has finished yet. The charts appear when the first candidate submits.</p></Panel> : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Time used" hint={`Share of the allowed ${d.duration_min} minutes. Shortest ${d.time_minutes.min} min, average ${d.time_minutes.avg} min, longest ${d.time_minutes.max} min.`}>
              <Histogram bins={d.time_distribution} xLabel="Time used (% of the allowed time)" name="Time used" data-testid="aa-time-hist" />
            </Panel>
            <Panel title="Score against time taken" hint="One dot per candidate. Colour shows the integrity risk level.">
              <Scatter points={d.points.map((p) => ({ x: p.minutes, y: p.percent, color: RISK_COLOR[p.risk] ?? COLOR.blue, label: `${p.name}: ${p.percent}% in ${p.minutes} min (risk ${RISK[p.risk] ?? p.risk})` }))} xMax={d.duration_min} data-testid="aa-scatter" />
              <Legend items={Object.entries(RISK_COLOR).map(([k, c]) => [c, RISK[k]])} />
            </Panel>
          </div>

          {d.sections.length > 0 && (
            <Panel title="Sections" hint="Average score of the finished candidates in each section." data-testid="aa-sections">
              {d.sections.map((x) => <Bar key={x.id} label={x.title} score={x.mean} max={100} text={`${x.mean}%`} averageText={`best ${x.best}% · lowest ${x.worst}%${x.below_min ? ` · ${x.below_min} below the section minimum` : ""}`} />)}
            </Panel>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            {GROUPS.filter(([k]) => d[k].length > 0).map(([k, title]) => (
              <Panel key={k} title={title} data-testid={`aa-${k}`}>
                {d[k].map((x) => <Bar key={x.name} label={`${cap(x.name)} (${x.n})`} score={x.percent} max={100} text={`${x.percent}%`} />)}
              </Panel>
            ))}
          </div>

          <Panel title="Questions" hint="Earned = average share of the marks. Separates = how well the question tells strong from weak candidates (needs six or more finished).">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} /> Only questions that need a look</label>
            <div className="hidden grid-cols-[1.5rem_1fr_6rem_5rem_4.5rem_5rem_8rem] gap-x-3 border-b px-1 pb-1 text-xs font-semibold text-muted-foreground sm:grid"><span>#</span><span>Question</span><span>Earned</span><span className="text-right">Full marks</span><span className="text-right">Blank</span><span className="text-right">Separates</span><span className="text-right">Verdict</span></div>
            {asked.map((q) => <QuestionRow key={q.question_id} q={q} n={d.questions.indexOf(q) + 1} />)}
            {asked.length === 0 && <p className="text-sm text-muted-foreground">No question needs a look.</p>}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Integrity" hint="Candidates by risk level." data-testid="aa-integrity"><Counts data={d.integrity} order={["low", "medium", "high", "critical"]} color={RISK_COLOR} /></Panel>
            <Panel title="Most common incidents" data-testid="aa-events">
              {d.events.length ? d.events.map((e) => <Bar key={e.type} label={cap(e.type.replace(/_/g, " "))} score={e.count} max={d.events[0].count} text={`${e.count}`} />) : <p className="text-sm text-muted-foreground">No incidents were recorded.</p>}
            </Panel>
            <Panel title="Plagiarism checks" hint="Candidates by level."><Counts data={d.plagiarism} order={["clear", "low", "medium", "high"]} /></Panel>
          </div>

          <Panel title="Marking" data-testid="aa-marking">
            <p className="text-sm">{m.machine} answers were marked by the platform (choice, coding, SQL). {m.ai} written answers got an AI mark{m.ai_changed ? `, ${m.ai_changed} of them changed by a person` : ""}. {m.person} answers were marked or changed by a person.</p>
            {Object.keys(d.languages).length > 0 && <><h3 className="text-sm font-semibold">Programming languages used</h3><Counts data={d.languages} /></>}
          </Panel>
        </>
      )}
    </div>
  )
}
