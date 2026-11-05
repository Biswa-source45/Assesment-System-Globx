import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Archive, Plus, RotateCcw } from "lucide-react"
import { toast } from "sonner"
import { del, get, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate } from "@/lib/labels"
import { useDepartments } from "@/lib/useDepartments"
import { useConfirm } from "@/components/ConfirmDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

// Can candidates start this exam right now? Read from the exam's own dates, which the admin can change at any time.
function windowOf(t) {
  if (t.status !== "published") return null
  if (t.starts_at && new Date(t.starts_at) > new Date()) return "Opens later"
  if (t.ends_at && new Date(t.ends_at) < new Date()) return "Closed"
  return "Open now"
}

export default function Exams() {
  const { byId } = useDepartments()
  const { user } = useAuth()
  const confirm = useConfirm()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState("")
  const [view, setView] = useState("active")  // "archived" is the Super Admin's window
  const archived = view === "archived"

  const [again, setAgain] = useState(0)
  const load = () => setAgain((n) => n + 1)
  useEffect(() => {  // an answer that arrives after the tab was switched (or asked again) is ignored, so it can never fill the wrong list
    let current = true
    get(archived ? "/tests?archived=true" : "/tests").then((r) => current && setRows(r)).catch((e) => current && setError(e.message))
    return () => { current = false }
  }, [archived, again])

  async function archive(t) {
    if (!(await confirm({ title: `Archive "${t.title}"?`, description: "It leaves the Exams list and the candidates no longer see it. Nothing is deleted: its questions, candidates and results stay, and you can restore it from the Archived tab.", action: "Archive", destructive: true }))) return
    try { await del(`/tests/${t.id}`); toast.success("Exam archived"); load() } catch (e) { toast.error(e.message) }
  }
  async function restore(t) {
    try { await post(`/tests/${t.id}/restore`); toast.success("Exam restored"); load() } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Exams</h1>
        {user.can.author && !archived && <Button asChild><Link to="/admin/exams/new"><Plus /> New exam</Link></Button>}
      </div>
      {user.can.super && (
        <Tabs value={view} onValueChange={(v) => { setRows(null); setView(v) }}>
          <TabsList><TabsTrigger value="active">Exams</TabsTrigger><TabsTrigger value="archived">Archived</TabsTrigger></TabsList>
        </Tabs>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead><TableHead>Department</TableHead><TableHead>Status</TableHead><TableHead>Available</TableHead><TableHead>Time</TableHead>
              <TableHead>Questions</TableHead><TableHead>Marks</TableHead><TableHead>Taken</TableHead><TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="max-w-64 font-medium whitespace-normal"><Link className="hover:underline" to={`/admin/exams/${t.id}`}>{t.title}</Link></TableCell>
                <TableCell>{byId[t.department_id]?.name ?? "-"}</TableCell>
                <TableCell>
                  <Badge variant={t.status === "published" ? "default" : "secondary"}>{t.status}</Badge>
                  {windowOf(t) && <div className="mt-1 text-xs text-muted-foreground" data-testid="exam-window">{windowOf(t)}</div>}
                </TableCell>
                <TableCell className="text-xs leading-5">
                  <div><span className="text-muted-foreground">From</span> {t.starts_at ? fmtDate(t.starts_at) : "any time"}</div>
                  <div><span className="text-muted-foreground">To</span> {t.ends_at ? fmtDate(t.ends_at) : "no end time"}</div>
                </TableCell>
                <TableCell>{t.duration_min} min</TableCell>
                <TableCell>{t.question_count}</TableCell>
                <TableCell>{t.total_marks}</TableCell>
                <TableCell>{t.taken} of {t.invited}</TableCell>
                <TableCell className="text-right">
                  {archived && <Button size="sm" className="mr-2" onClick={() => restore(t)}><RotateCcw /> Restore</Button>}
                  {!archived && t.status === "published" && <Button asChild variant="outline" size="sm" className="mr-2 border-primary text-primary hover:bg-primary/10"><Link to={`/admin/monitor?exam=${t.id}`}>Monitor</Link></Button>}
                  <Button asChild size="sm"><Link to={`/admin/exams/${t.id}`}>Open</Link></Button>
                  {user.can.super && !archived && <Button variant="ghost" size="icon-sm" className="ml-1" aria-label={`Archive ${t.title}`} title="Archive" onClick={() => archive(t)}><Archive /></Button>}
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && <TableRow><TableCell colSpan={8} className="text-muted-foreground">{archived ? "No archived exams." : "No exams yet. Create one to get started."}</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
