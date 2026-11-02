import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import { api, get } from "@/lib/api"
import { ENDED, RISK, STATUS } from "@/lib/labels"
import { hms, useCountdown } from "@/lib/useCountdown"
import AssignmentActions from "@/components/AssignmentActions"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const POLL_MS = 5000
const FINISHED = ["submitted", "auto_submitted", "evaluating", "review_pending", "evaluated", "test_taken"]

function TimeLeft({ deadline, skew }) {
  const left = useCountdown(deadline, skew)
  return <span className={"font-mono " + (left != null && left < 300 ? "font-medium text-destructive" : "")} data-testid="time-left">{hms(left)}</span>
}

// Snapshots are protected files, so they are fetched with the login header and shown from memory.
function Snapshot({ id }) {
  const [url, setUrl] = useState(null)
  const shown = useRef(null)
  useEffect(() => {
    if (!id) return
    let alive = true
    api(`/snapshots/${id}`, { raw: true })
      .then((r) => r.blob())
      .then((b) => {
        if (!alive) return
        const next = URL.createObjectURL(b)
        if (shown.current) URL.revokeObjectURL(shown.current)
        shown.current = next
        setUrl(next)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [id])
  useEffect(() => () => { if (shown.current) URL.revokeObjectURL(shown.current) }, [])
  if (!id) return <span className="text-xs text-muted-foreground">-</span>
  return url ? <img src={url} alt="Latest camera snapshot" className="h-16 w-20 rounded object-cover" /> : <span className="inline-block h-16 w-20 rounded bg-muted" />
}

const ago = (s) => (s == null ? "-" : s < 60 ? `${s}s ago` : `${Math.floor(s / 60)} min ago`)
const riskVariant = { low: "secondary", medium: "outline", high: "destructive", critical: "destructive" }

export default function Monitor() {
  const [params, setParams] = useSearchParams()
  const examId = params.get("exam")
  const [exams, setExams] = useState(null)
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [updated, setUpdated] = useState(null)

  useEffect(() => {
    get("/tests")
      .then((list) => {
        const published = list.filter((t) => t.status === "published")
        setExams(published)
        if (!examId && published.length) setParams({ exam: published[0].id }, { replace: true })
      })
      .catch((e) => setError(e.message))
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(() => {
    if (!examId) return
    get(`/tests/${examId}/monitor`)
      .then((d) => { setData({ ...d, skew: new Date(d.server_time).getTime() - Date.now() }); setUpdated(new Date()); setError("") })
      .catch((e) => setError(e.message))
  }, [examId])

  useEffect(() => {
    setData(null)
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  const rows = data?.rows ?? []
  const count = (fn) => rows.filter(fn).length

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Live monitor</h1>
        <div className="flex items-center gap-2">
          {exams?.length > 0 && (
            <Select value={examId ?? ""} onValueChange={(v) => setParams({ exam: v })}>
              <SelectTrigger className="w-72" aria-label="Exam"><SelectValue placeholder="Choose an exam" /></SelectTrigger>
              <SelectContent>{exams.map((t) => <SelectItem key={t.id} value={t.id}>{t.title}</SelectItem>)}</SelectContent>
            </Select>
          )}
          <Button variant="outline" size="icon" aria-label="Refresh now" onClick={load}><RefreshCw /></Button>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {exams && !exams.length && <p className="text-muted-foreground">No exam is published. Publish an exam to watch it here.</p>}

      {data && (
        <>
          <div className="flex flex-wrap gap-2 text-sm" data-testid="monitor-summary">
            <Badge>{count((r) => r.status === "in_progress")} in progress</Badge>
            <Badge variant="secondary">{count((r) => r.status === "invited")} not started</Badge>
            <Badge variant="secondary">{count((r) => FINISHED.includes(r.status) && r.assignment_status !== "banned")} submitted</Badge>
            <Badge variant={count((r) => r.assignment_status === "banned") ? "destructive" : "secondary"}>{count((r) => r.assignment_status === "banned")} locked</Badge>
            <span className="self-center text-xs text-muted-foreground">Updated {updated?.toLocaleTimeString()}, refreshes every {POLL_MS / 1000} s</span>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candidate</TableHead><TableHead>Status</TableHead><TableHead>Time left</TableHead><TableHead>Answered</TableHead>
                <TableHead>Window leaves</TableHead><TableHead>Face issues</TableHead><TableHead>Risk</TableHead><TableHead>Last signal</TableHead><TableHead>Camera</TableHead><TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => {
                const at = r.attempt
                const live = r.status === "in_progress"
                const silent = live && data.limits.webcam && (at.snapshot_age_s ?? at.last_seen_s ?? 0) > Math.max(45, 3 * data.limits.snapshot_s)
                return (
                  <TableRow key={r.assignment_id} data-testid="monitor-row">
                    <TableCell><div className="font-medium">{r.name}</div><div className="font-mono text-xs text-muted-foreground">{r.username}</div></TableCell>
                    <TableCell>
                      <Badge variant={live ? "default" : r.assignment_status === "banned" ? "destructive" : "secondary"} data-testid="monitor-status">{STATUS[r.assignment_status === "banned" ? "banned" : r.status] ?? r.status}</Badge>
                      {at && !live && <div className="mt-1 text-xs text-muted-foreground">{ENDED[at.submit_reason] ?? ""}</div>}
                    </TableCell>
                    <TableCell>{live ? <TimeLeft deadline={at.deadline_at} skew={data.skew} /> : "-"}</TableCell>
                    <TableCell>{at ? `${at.answered} / ${at.total}` : "-"}</TableCell>
                    <TableCell>{at ? <Badge variant={at.violations ? "destructive" : "secondary"} data-testid="monitor-leaves">{at.violations}{data.limits.tab ? ` / ${data.limits.tab}` : ""}</Badge> : "-"}</TableCell>
                    <TableCell>{at && data.limits.webcam ? <Badge variant={at.face_incidents ? "destructive" : "secondary"} data-testid="monitor-faces">{at.face_incidents}{data.limits.face ? ` / ${data.limits.face}` : ""}</Badge> : "-"}</TableCell>
                    <TableCell>{at ? <Badge variant={riskVariant[at.risk_level] ?? "secondary"}>{RISK[at.risk_level] ?? at.risk_level}</Badge> : "-"}</TableCell>
                    <TableCell className={silent ? "font-medium text-destructive" : "text-muted-foreground"}>{live ? (silent ? "No camera signal" : ago(at.last_seen_s)) : "-"}</TableCell>
                    <TableCell>{at && data.limits.webcam ? <Snapshot id={at.snapshot_id} /> : "-"}</TableCell>
                    <TableCell className="text-right">
                      <AssignmentActions row={{ id: r.assignment_id, name: r.name, username: r.username, status: r.status, assignmentStatus: r.assignment_status }} onDone={load} />
                    </TableCell>
                  </TableRow>
                )
              })}
              {!rows.length && <TableRow><TableCell colSpan={10} className="text-muted-foreground">No participants yet. Add them on the exam's Participants tab.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  )
}
