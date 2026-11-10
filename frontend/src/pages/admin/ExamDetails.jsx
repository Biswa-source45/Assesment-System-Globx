import { useEffect, useState } from "react"
import { toast } from "sonner"
import { post, put } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fromHtml, toHtml } from "@/lib/html"
import { fromLocalInput, toLocalInput } from "@/lib/labels"
import { useDepartments } from "@/lib/useDepartments"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

// What the server assumes when a setting is missing (see proctoring_config in services/attempts.py).
const PROCTORING = { enabled: true, webcam: true, fullscreen: true, tab_switch_limit: 3, face_limit: 5, face_min_seconds: 3, block_paste: true, snapshot_seconds: 15, block_multi_display: true,
  evidence: "pictures", screen_share: false, live_view: false, screenshot_seconds: 60, video_retention_days: 14 }

const toForm = (t) => ({
  department_id: t?.department_id ?? "", title: t?.title ?? "", description: t?.description ?? "", instructions: fromHtml(t?.instructions ?? ""),
  duration_min: t?.duration_min ?? 60, starts_at: toLocalInput(t?.starts_at), ends_at: toLocalInput(t?.ends_at), cutoff: t?.cutoff ?? 0,
  shuffle_questions: t?.shuffle_questions ?? true, shuffle_options: t?.shuffle_options ?? true,
  show_result: t?.settings?.show_result_to_candidate ?? true, min_question_seconds: t ? (t.settings?.min_question_seconds ?? 0) : 5, proctoring: { ...PROCTORING, ...(t?.settings?.proctoring ?? {}) },
})

function toBody(f, t) {
  const p = f.proctoring
  return {
    department_id: f.department_id, title: f.title, description: f.description, instructions: toHtml(f.instructions), duration_min: Number(f.duration_min),
    starts_at: fromLocalInput(f.starts_at), ends_at: fromLocalInput(f.ends_at), access_enabled: t?.access_enabled ?? true,
    cutoff: Number(f.cutoff) || 0, shuffle_questions: f.shuffle_questions, shuffle_options: f.shuffle_options,
    settings: {
      ...(t?.settings ?? {}), show_result_to_candidate: f.show_result, min_question_seconds: Math.max(0, Math.min(60, Math.floor(Number(f.min_question_seconds)) || 0)),
      proctoring: {
        ...(t?.settings?.proctoring ?? {}), ...p, tab_switch_limit: Number(p.tab_switch_limit), face_limit: Number(p.face_limit),
        face_min_seconds: Number(p.face_min_seconds), snapshot_seconds: Number(p.snapshot_seconds),
        screenshot_seconds: Number(p.screenshot_seconds), video_retention_days: Number(p.video_retention_days),
      },
    },
  }
}

function Toggle({ id, label, hint, checked, onChange, disabled }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="grid gap-0.5">
        <Label htmlFor={id}>{label}</Label>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  )
}

function Field({ id, label, hint, ...props }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} {...props} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

// test === null creates a new exam; otherwise it edits that one. onSaved receives the exam the server returns.
export default function ExamDetails({ test, onSaved }) {
  const [f, setF] = useState(() => toForm(test))
  const { departments } = useDepartments()
  const author = useAuth().user.can.author  // everyone else may look, not change
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  useEffect(() => { if (!test && departments?.length && !f.department_id) set("department_id", departments[0].id) }, [departments])  // eslint-disable-line react-hooks/exhaustive-deps
  const setP = (k, v) => setF((x) => ({ ...x, proctoring: { ...x.proctoring, [k]: v } }))
  const p = f.proctoring

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const out = test ? await put(`/tests/${test.id}`, toBody(f, test)) : await post("/tests", toBody(f, null))
      toast.success(test ? "Exam saved" : "Exam created. Now add its questions.")
      onSaved(out)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="max-w-3xl"><fieldset disabled={!author} className="m-0 grid min-w-0 gap-4 border-0 p-0">
      <Card>
        <CardHeader><CardTitle>Exam</CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-1.5">
            <Label>Department</Label>
            <Select value={f.department_id} onValueChange={(v) => set("department_id", v)}>
              <SelectTrigger className="w-64" aria-label="Department"><SelectValue placeholder="Choose a department" /></SelectTrigger>
              <SelectContent>{(departments ?? []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">Who this exam is for. Auto populate and the question picker start with this department's questions.</p>
          </div>
          <Field id="exam-title" label="Title" required value={f.title} onChange={(e) => set("title", e.target.value)} />
          <div className="grid gap-1.5">
            <Label htmlFor="exam-desc">Description</Label>
            <Textarea id="exam-desc" value={f.description} onChange={(e) => set("description", e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="exam-instr">Instructions shown to candidates before they start</Label>
            <Textarea id="exam-instr" className="min-h-28" value={f.instructions} onChange={(e) => set("instructions", e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Schedule and rules</CardTitle><CardDescription>Candidates can start only between the start and end time. Leave both empty to keep the exam open whenever it is published.</CardDescription></CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Field id="exam-start" label="Opens at" type="datetime-local" value={f.starts_at} onChange={(e) => set("starts_at", e.target.value)} />
            <Field id="exam-end" label="Closes at" type="datetime-local" value={f.ends_at} onChange={(e) => set("ends_at", e.target.value)}
              hint="Takes effect at once, also for people taking the exam now. Move it later to let more people take the exam; results are calculated after this time." />
            <Field id="exam-duration" label="Time allowed per candidate (minutes)" type="number" min="1" max="600" value={f.duration_min} onChange={(e) => set("duration_min", e.target.value)} />
            <Field id="exam-cutoff" label="Pass mark (total marks)" type="number" min="0" step="0.5" value={f.cutoff} onChange={(e) => set("cutoff", e.target.value)}
              hint="0 means no pass mark: scores are shown without a Passed or Not passed verdict. Someone who answers nothing is never shown as passed." />
            <Field id="exam-read" label="Seconds each question stays on screen before Next unlocks" type="number" min="0" max="60" value={f.min_question_seconds} onChange={(e) => set("min_question_seconds", e.target.value)}
              hint="Stops people clicking through without reading. 0 turns it off. Counted the first time a candidate opens each question." />
          </div>
          <Toggle id="shuffle-q" label="Shuffle question order" checked={f.shuffle_questions} onChange={(v) => set("shuffle_questions", v)} />
          <Toggle id="shuffle-o" label="Shuffle answer options" checked={f.shuffle_options} onChange={(v) => set("shuffle_options", v)} />
          <Toggle id="show-result" label="Show the result to the candidate" hint="Off: they only see that their answers were received." checked={f.show_result} onChange={(v) => set("show_result", v)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Proctoring</CardTitle><CardDescription>Applies to everyone who takes this exam.</CardDescription></CardHeader>
        <CardContent className="grid gap-4">
          <Toggle id="p-enabled" label="Proctoring on" checked={p.enabled} onChange={(v) => setP("enabled", v)} />
          {p.enabled && (
            <>
              <Toggle id="p-webcam" label="Camera and face check" hint="Needs exactly one face before the exam starts and during it." checked={p.webcam} onChange={(v) => setP("webcam", v)} />
              <Toggle id="p-fs" label="Full screen" checked={p.fullscreen} onChange={(v) => setP("fullscreen", v)} />
              <Toggle id="p-paste" label="Block copy, paste and right-click" checked={p.block_paste} onChange={(v) => setP("block_paste", v)} />
              <Toggle id="p-display" label="Block a second screen" checked={p.block_multi_display} onChange={(v) => setP("block_multi_display", v)} />
              <Toggle id="p-screen" label="Candidate shares their entire screen" hint="Needed for screen pictures, screen video and the live screen. Stopping the share counts like leaving the window." checked={p.screen_share} onChange={(v) => setP("screen_share", v)} />
              <Toggle id="p-live" label="Live view for the invigilator" hint="Watch every camera and screen in the Live monitor, send a message or talk to one candidate. Candidates should wear headphones." checked={p.live_view} onChange={(v) => setP("live_view", v)} />
              <div className="grid gap-1.5">
                <Label>What is kept for the whole exam</Label>
                <Select value={p.evidence} onValueChange={(v) => setP("evidence", v)}>
                  <SelectTrigger className="w-80" aria-label="Evidence kept"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pictures">Pictures (camera, and the screen if shared)</SelectItem>
                    <SelectItem value="video">Video of the whole exam (camera, and the screen if shared)</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">{p.evidence === "video" ? "About 150 MB per candidate for a 90-minute exam. Deleted automatically after the number of days below." : "A few MB per candidate. Pictures are kept."}</p>
              </div>
              {p.evidence === "video" && <Field id="p-days" label="Delete the video after (days)" type="number" min="1" max="90" value={p.video_retention_days} onChange={(e) => setP("video_retention_days", e.target.value)} hint="Counted from the end of the candidate's exam." />}
              {p.evidence === "pictures" && p.screen_share && <Field id="p-shot" label="Screen picture every (seconds)" type="number" min="10" max="300" value={p.screenshot_seconds} onChange={(e) => setP("screenshot_seconds", e.target.value)} />}
              <div className="grid gap-4 md:grid-cols-2">
                <Field id="p-tab" label="Window or full-screen leaves allowed" type="number" min="0" max="20" value={p.tab_switch_limit} onChange={(e) => setP("tab_switch_limit", e.target.value)}
                  hint="Each one shows a warning. The next one ends the exam. 0 turns the rule off." />
                {p.webcam && (
                  <>
                    <Field id="p-face" label="Face warnings before the exam ends and the login is locked" type="number" min="0" max="20" value={p.face_limit} onChange={(e) => setP("face_limit", e.target.value)}
                      hint="Counts no face, or more than one face. 0 turns the rule off." />
                    <Field id="p-facesec" label="Seconds a face problem must last to count" type="number" min="1" max="30" value={p.face_min_seconds} onChange={(e) => setP("face_min_seconds", e.target.value)} />
                    <Field id="p-snap" label="Camera snapshot every (seconds)" type="number" min="5" max="120" value={p.snapshot_seconds} onChange={(e) => setP("snapshot_seconds", e.target.value)} />
                  </>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
      {author && <div><Button type="submit" disabled={busy}>{busy ? "Saving..." : test ? "Save exam" : "Create exam"}</Button></div>}
    </fieldset></form>
  )
}
