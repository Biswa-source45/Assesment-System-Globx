import { useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { toast } from "sonner"
import { Flag } from "lucide-react"
import { get, post, put } from "@/lib/api"
import { getCamera, stopCamera } from "@/lib/media"
import { useEvidence } from "@/lib/useEvidence"
import { Proctor } from "@/lib/proctor"
import { hms, useCountdown } from "@/lib/useCountdown"
import { Badge } from "@/components/ui/badge"
import Brand from "@/components/Brand"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { CodeView, SqlSamples } from "@/pages/candidate/CodeView"
import { Html, McqView, TextView } from "@/pages/candidate/questions"

const isCode = (q) => q.type === "coding" || q.type === "sql"
const isAnswered = (q, r) => {
  if (!r) return false
  if (q.type.startsWith("mcq")) return (r.selected ?? []).length > 0
  if (isCode(q)) return !!(r.submitted || r.best_submission_id)
  return (r.text ?? "").trim() !== ""
}
const goFullscreen = () => document.documentElement.requestFullscreen().catch(() => toast.error("Your browser blocked full screen. Press F11."))

export default function Exam() {
  const { attemptId } = useParams()
  const navigate = useNavigate()
  const [st, setSt] = useState(null)
  const [error, setError] = useState("")
  const [sec, setSec] = useState(0)
  const [qi, setQi] = useState(0)
  const [resp, setResp] = useState({})
  const [flags, setFlags] = useState({})
  const [saved, setSaved] = useState("")
  const [warn, setWarn] = useState("")
  const [fsNeeded, setFsNeeded] = useState(false)
  const [endOpen, setEndOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [info, setInfo] = useState({})
  const [deadline, setDeadline] = useState(null)  // the server's deadline, refreshed by syncClock
  const [faces, setFaces] = useState(null)
  const respRef = useRef({})
  const flagRef = useRef({})
  const seqs = useRef({})
  const dirty = useRef(new Set())
  const timers = useRef({})
  const skew = useRef(0)
  const version = useRef(null)  // the content version the screen shows; the server's moves when the examiner saves a question
  const video = useRef(null)
  const proctor = useRef(null)
  const finished = useRef(false)
  const latest = useRef({})  // newest callbacks, so timers and the proctor never use stale ones
  const cfg = st?.test.proctoring ?? {}
  const ev = useEvidence({ st, cfg, attemptId, proctorRef: proctor })  // screen, video, live view, the invigilator's voice and messages

  useEffect(() => {
    get(`/attempts/${attemptId}`)
      .then((d) => {
        if (d.attempt.status !== "in_progress") { navigate(`/exam/done/${attemptId}`, { replace: true }); return }
        skew.current = new Date(d.attempt.server_time).getTime() - Date.now()
        version.current = d.attempt.content_version
        const r = {}, f = {}
        Object.entries(d.answers).forEach(([k, v]) => { r[k] = v.response; f[k] = v.flagged; seqs.current[k] = v.seq || 0 })
        respRef.current = r
        flagRef.current = f
        setResp(r)
        setFlags(f)
        setInfo({ violations: d.attempt.violations })
        setDeadline(d.attempt.deadline_at)
        setSt(d)
      })
      .catch((e) => setError(e.message))
  }, [attemptId, navigate])

  const sections = st?.sections ?? []
  const curSec = sections[sec]
  const q = curSec?.questions[qi]
  const left = useCountdown(deadline, skew.current)
  const secLeft = useCountdown(curSec?.deadline, skew.current)

  // ---- saving
  async function flushOne(qid) {
    seqs.current[qid] = (seqs.current[qid] || 0) + 1
    try {
      await put(`/attempts/${attemptId}/answers/${qid}`, { response: respRef.current[qid] ?? {}, flagged: !!flagRef.current[qid], seq: seqs.current[qid] })
      dirty.current.delete(qid)
      setSaved(new Date().toLocaleTimeString())
    } catch (e) {
      if (e.status === 409) dirty.current.delete(qid)
      else if (e.status === 423) latest.current.syncClock()  // time is over, or an admin ended the exam: the clock says which
      else if (e.status === 403) { dirty.current.delete(qid); toast.error(e.message) }
      else setSaved("offline, retrying")
    }
  }
  async function flushAll() { for (const qid of [...dirty.current]) await flushOne(qid) }

  function update(qid, patch, immediate = false) {
    respRef.current = { ...respRef.current, [qid]: { ...respRef.current[qid], ...patch } }
    setResp(respRef.current)
    dirty.current.add(qid)
    clearTimeout(timers.current[qid])
    timers.current[qid] = setTimeout(() => flushOne(qid), immediate ? 50 : 1500)
  }
  function toggleFlag(qid) {
    flagRef.current = { ...flagRef.current, [qid]: !flagRef.current[qid] }
    setFlags(flagRef.current)
    dirty.current.add(qid)
    flushOne(qid)
  }

  // ---- sections
  async function enterSection(i) {
    const s = sections[i]
    if (!s) return
    try {
      const r = await post(`/attempts/${attemptId}/sections/${s.id}/enter`)
      setSt((x) => ({ ...x, sections: x.sections.map((ss) => ({ ...ss, deadline: r.section_state[ss.id]?.deadline ?? ss.deadline, closed: !!r.section_state[ss.id]?.closed })) }))
    } catch (e) { toast.error(e.message); return }
    await flushAll()
    setSec(i)
    setQi(0)
  }

  // ---- finishing
  function leaveExam() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    stopCamera()
  }
  // Ask the server what the clock says. An admin may have extended the time or ended the exam.
  const REASON = { admin_ended: "ended", time_over: "time", violation_limit: "force_submit", face_violation: "ban" }
  // The examiner saved a question: load the new text, options and marks. Answers, position and section timers stay as they are.
  async function refreshQuestions() {
    const fresh = await get(`/attempts/${attemptId}`)
    const before = Object.fromEntries(sections.flatMap((s) => s.questions).map((x) => [x.id, JSON.stringify(x)]))
    const changed = fresh.sections.flatMap((s) => s.questions).filter((x) => before[x.id] !== JSON.stringify(x))
    version.current = fresh.attempt.content_version
    setSt((x) => ({
      ...x, attempt: { ...x.attempt, max_score: fresh.attempt.max_score },
      sections: x.sections.map((s) => { const n = fresh.sections.find((f) => f.id === s.id); return n ? { ...n, deadline: s.deadline, closed: s.closed } : s }),
    }))
    if (changed.length) toast.info(`The examiner updated ${changed.length === 1 ? `"${changed[0].title}"` : `${changed.length} questions`}. Your answers are kept.`)
  }
  async function syncClock() {
    try {
      const c = await get(`/attempts/${attemptId}/clock`)
      if (c.status === "in_progress") {
        skew.current = new Date(c.server_time).getTime() - Date.now()
        setDeadline(c.deadline_at)
        if (c.content_version !== version.current) await refreshQuestions()
        return
      }
      if (finished.current) return
      finished.current = true  // the server already ended it: no submit, just leave
      proctor.current?.stop()
      ev.stop()
      leaveExam()
      navigate(`/exam/done/${attemptId}?why=${REASON[c.reason] ?? "submitted"}`, { replace: true })
    } catch { /* offline: the next tick tries again */ }
  }

  async function finish(why) {
    if (finished.current) return
    finished.current = true
    setBusy(true)
    try { await flushAll() } catch { /* the server grades what it has */ }
    try { await proctor.current?.flush() } catch { /* same */ }
    try { await ev.stop() } catch { /* the last pieces of video are best effort */ }
    proctor.current?.stop()
    try { await post(`/attempts/${attemptId}/submit`, { reason: why }) } catch { /* already submitted */ }
    leaveExam()
    navigate(`/exam/done/${attemptId}?why=${why}`, { replace: true })
  }
  function onProctor(r) {
    if (r.action === "fullscreen_required") { setFsNeeded(true); return }
    if (r.violations !== undefined) setInfo({ violations: r.violations, limit: r.limit, faceIncidents: r.face_incidents, faceLimit: r.face_limit })
    if (r.action === "warn" && r.message) setWarn(r.message)
    if (r.action === "force_submit" || r.action === "ban") {  // the server already ended the exam
      finished.current = true
      proctor.current?.stop()
      leaveExam()
      navigate(`/exam/done/${attemptId}?why=${r.action}`, { replace: true })
    }
  }
  latest.current = { finish, onProctor, flushAll, syncClock }

  useEffect(() => { if (st) enterSection(0) }, [!!st])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (st && left === 0) finish("time") }, [left])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const save = setInterval(() => latest.current.flushAll(), 10000)
    const clock = setInterval(() => latest.current.syncClock(), 15000)
    return () => { clearInterval(save); clearInterval(clock) }
  }, [])
  useEffect(() => {  // a section whose timer ran out closes; move on to the next open one
    if (!st || !curSec?.deadline || secLeft !== 0) return
    toast.error(`Time for "${curSec.title}" is over`)
    setSt((x) => ({ ...x, sections: x.sections.map((s) => (s.id === curSec.id ? { ...s, closed: true } : s)) }))
    const next = sections.findIndex((s, i) => i > sec && !s.closed)
    if (next >= 0) enterSection(next)
  }, [secLeft])  // eslint-disable-line react-hooks/exhaustive-deps

  // ---- proctoring
  useEffect(() => {
    if (!st || !cfg.enabled) return
    let p
    ;(async () => {
      if (cfg.webcam) {
        try {
          const stream = await getCamera()
          video.current.srcObject = stream
          await video.current.play().catch(() => {})
        } catch { /* a missing camera shows up as "no face" and counts against the candidate */ }
      }
      p = new Proctor({ attemptId, cfg, video: video.current, screenVideo: ev.screenVideo.current, onResult: (r) => latest.current.onProctor(r), onFaces: setFaces })
      proctor.current = p
      p.start()
      ev.begin()
      if (cfg.fullscreen && !document.fullscreenElement) setFsNeeded(true)
    })()
    return () => { p?.flush(); p?.stop() }
  }, [!!st])  // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="p-8 text-destructive">{error}</div>
  if (!st || !curSec) return <div className="p-8 text-muted-foreground">Loading your exam...</div>

  const answeredIn = (s) => s.questions.filter((x) => isAnswered(x, resp[x.id])).length
  const all = sections.flatMap((s) => s.questions)
  const unanswered = all.length - all.filter((x) => isAnswered(x, resp[x.id])).length
  const go = (i) => { flushAll(); setQi(i) }
  const faceBad = cfg.webcam && faces !== null && faces !== 1

  return (
    <div className="min-h-svh bg-muted/40 pb-32">
      <video ref={ev.screenVideo} muted playsInline className="pointer-events-none fixed top-0 left-0 size-px opacity-0" />
      {ev.talk && <div role="status" data-testid="talk-banner" className="fixed inset-x-0 top-0 z-[60] bg-red-600 py-2 text-center text-sm font-medium text-white">The invigilator is speaking with you. Your microphone is on.</div>}
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b bg-white px-4 py-2.5">
        <Brand />
        <b className="grow truncate">{st.test.title}</b>
        {cfg.enabled && <Badge variant="secondary">Proctoring on</Badge>}
        {cfg.enabled && cfg.tab_switch_limit > 0 && (
          <Badge variant={info.violations ? "destructive" : "secondary"} data-testid="violations">Warnings {info.violations ?? 0} / {cfg.tab_switch_limit}</Badge>
        )}
        {curSec.deadline && <span className="text-sm" title="Section time left">Section {hms(secLeft)}</span>}
        <span data-testid="timer" className={"rounded-md px-3 py-1 font-heading text-lg font-semibold " + (left != null && left < 300 ? "bg-destructive text-white" : "bg-primary text-white")}>{hms(left)}</span>
        <Button size="sm" variant="secondary" onClick={() => { flushAll(); setEndOpen(true) }}>End exam</Button>
      </header>

      <div className="mx-auto grid max-w-6xl gap-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid gap-4">
        <div className="flex flex-wrap gap-2">
          {sections.map((s, i) => (
            <Button key={s.id} size="sm" variant={i === sec ? "default" : "outline"} disabled={s.closed && i !== sec} onClick={() => i !== sec && enterSection(i)}>
              {s.title} · {answeredIn(s)}/{s.count}{s.closed ? " (closed)" : ""}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" aria-label="Question palette">
          {curSec.questions.map((x, i) => (
            <button key={x.id} onClick={() => go(i)} aria-label={`Question ${i + 1}`}
              className={"size-8 rounded-md border text-sm font-medium " + (i === qi ? "ring-2 ring-ring " : "") +
                (isAnswered(x, resp[x.id]) ? "border-primary bg-primary text-white" : flags[x.id] ? "border-destructive text-destructive" : "bg-white")}>{i + 1}</button>
          ))}
          <span className="ml-2 self-center text-xs text-muted-foreground">Blue = answered, red outline = marked for review</span>
        </div>
        </div>
        {cfg.enabled && cfg.webcam && (
          <div className={"w-40 shrink-0 overflow-hidden rounded-lg border-2 bg-black " + (faceBad ? "border-destructive" : "border-green-600")} data-testid="camera-box">
            <video ref={video} muted playsInline className="aspect-[4/3] w-full object-cover" />
            <div className={"px-2 py-1 text-center text-xs " + (faceBad ? "bg-destructive text-white" : "text-white")}>
              {faces === null ? "Camera starting" : faces === 1 ? "Face OK" : faces === 0 ? "No face!" : `${faces} faces!`}
              {info.faceLimit ? ` · ${info.faceIncidents ?? 0}/${info.faceLimit}` : ""}
            </div>
          </div>
        )}
      </div>

        {q && (
          <div className={isCode(q) ? "grid gap-4 lg:grid-cols-[2fr_3fr]" : "grid gap-4"}>
            <Card>
              <CardContent className="grid gap-3 pt-6">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <h2 className="text-xl font-semibold">{q.title}</h2>
                  <div className="flex gap-1.5">
                    <Badge>+{q.marks} marks</Badge>
                    {q.negative > 0 && <Badge variant="destructive">-{q.negative} wrong</Badge>}
                    <Badge variant="secondary">{q.difficulty}</Badge>
                  </div>
                </div>
                {q.group && <div className="rounded-md border bg-muted p-3"><h3 className="font-medium">{q.group.title}</h3><Html html={q.group.stimulus} /></div>}
                <Html html={q.body} />
                {q.type === "sql" && <SqlSamples q={q} />}
                {q.type === "coding" && q.open_cases.map((c) => (
                  <div key={c.ordinal} className="grid gap-1 text-xs">
                    <b className="text-sm">Sample {c.ordinal}</b>
                    <div className="grid gap-2 md:grid-cols-2">
                      <pre className="whitespace-pre-wrap rounded bg-muted p-2">{c.input}</pre>
                      <pre className="whitespace-pre-wrap rounded bg-muted p-2">{c.expected}</pre>
                    </div>
                  </div>
                ))}
                {curSec.closed && <p className="text-sm text-destructive">This section is closed. Answers can no longer be changed.</p>}
                {q.type.startsWith("mcq") && <McqView key={q.id} q={q} r={resp[q.id] ?? {}} closed={curSec.closed} onChange={(p, imm) => update(q.id, p, imm)} />}
                {(q.type === "short" || q.type === "long") && <TextView key={q.id} q={q} r={resp[q.id] ?? {}} closed={curSec.closed} onChange={(p, imm) => update(q.id, p, imm)} />}
              </CardContent>
            </Card>
            {isCode(q) && (
              <Card>
                <CardContent className="pt-6">
                  <CodeView key={q.id} q={q} r={resp[q.id] ?? {}} attemptId={attemptId} closed={curSec.closed} blockPaste={!!cfg.block_paste}
                    onChange={(p, imm) => update(q.id, p, imm)} />
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {q && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              <Button variant="outline" disabled={qi === 0} onClick={() => go(qi - 1)}>Previous</Button>
              <Button variant="outline" onClick={() => toggleFlag(q.id)}><Flag /> {flags[q.id] ? "Unmark review" : "Mark for review"}</Button>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground">{saved && `Saved ${saved}`}</span>
              {qi < curSec.questions.length - 1
                ? <Button onClick={() => go(qi + 1)}>Save and next</Button>
                : sec < sections.length - 1
                  ? <Button onClick={() => enterSection(sec + 1)}>Next section</Button>
                  : <Button onClick={() => { flushAll(); setEndOpen(true) }}>Finish</Button>}
            </div>
          </div>
        )}
      </div>

      <Dialog open={!!warn} onOpenChange={(o) => !o && setWarn("")}>
        <DialogContent showCloseButton={false}>
          <DialogHeader><DialogTitle className="text-destructive">Proctoring warning</DialogTitle><DialogDescription>{warn}</DialogDescription></DialogHeader>
          <DialogFooter><Button onClick={() => { setWarn(""); if (cfg.fullscreen && !document.fullscreenElement) goFullscreen() }}>I understand, continue</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!ev.message} onOpenChange={(o) => !o && ev.setMessage("")}>
        <DialogContent showCloseButton={false}>
          <DialogHeader><DialogTitle>Message from the invigilator</DialogTitle><DialogDescription data-testid="invigilator-message">{ev.message}</DialogDescription></DialogHeader>
          <DialogFooter><Button onClick={() => ev.setMessage("")}>OK</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={ev.screenNeeded && !warn}>
        <DialogContent showCloseButton={false}>
          <DialogHeader><DialogTitle>Share your screen to continue</DialogTitle><DialogDescription>This exam needs your entire screen to be shared. Stopping it is recorded as a warning. Choose Entire screen, then press Share.</DialogDescription></DialogHeader>
          <DialogFooter><Button onClick={ev.shareAgain}>Share my screen</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={fsNeeded && !warn}>
        <DialogContent showCloseButton={false}>
          <DialogHeader><DialogTitle>Full screen required</DialogTitle><DialogDescription>This exam must be taken in full screen. Leaving it is recorded as a warning.</DialogDescription></DialogHeader>
          <DialogFooter><Button onClick={async () => { await goFullscreen(); if (document.fullscreenElement) setFsNeeded(false) }}>Return to full screen</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={endOpen} onOpenChange={setEndOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>End the exam?</DialogTitle>
            <DialogDescription>
              {unanswered ? `${unanswered} question(s) are unanswered. ` : "All questions are answered. "}
              {all.some(isCode) && "Coding answers count only after you press Submit on each question. "}You cannot return after submitting.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEndOpen(false)}>Keep working</Button>
            <Button disabled={busy} onClick={() => finish("user")}>{busy ? "Submitting..." : "Submit exam"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

