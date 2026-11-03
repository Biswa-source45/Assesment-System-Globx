import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Plus } from "lucide-react"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate } from "@/lib/labels"
import { useDepartments } from "@/lib/useDepartments"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  const [rows, setRows] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/tests").then(setRows).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Exams</h1>
        {user.can.author && <Button asChild><Link to="/admin/exams/new"><Plus /> New exam</Link></Button>}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead><TableHead>Department</TableHead><TableHead>Status</TableHead><TableHead>Opens</TableHead><TableHead>Closes</TableHead><TableHead>Time</TableHead>
              <TableHead>Questions</TableHead><TableHead>Marks</TableHead><TableHead>Invited</TableHead><TableHead>Taken</TableHead><TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="font-medium"><Link className="hover:underline" to={`/admin/exams/${t.id}`}>{t.title}</Link></TableCell>
                <TableCell>{byId[t.department_id]?.name ?? "-"}</TableCell>
                <TableCell>
                  <Badge variant={t.status === "published" ? "default" : "secondary"}>{t.status}</Badge>
                  {windowOf(t) && <div className="mt-1 text-xs text-muted-foreground" data-testid="exam-window">{windowOf(t)}</div>}
                </TableCell>
                <TableCell>{fmtDate(t.starts_at)}</TableCell>
                <TableCell>{t.ends_at ? fmtDate(t.ends_at) : "No end time"}</TableCell>
                <TableCell>{t.duration_min} min</TableCell>
                <TableCell>{t.question_count}</TableCell>
                <TableCell>{t.total_marks}</TableCell>
                <TableCell>{t.invited}</TableCell>
                <TableCell>{t.taken}</TableCell>
                <TableCell className="text-right">
                  {t.status === "published" && <Button asChild variant="ghost" size="sm"><Link to={`/admin/monitor?exam=${t.id}`}>Monitor</Link></Button>}
                  <Button asChild variant="ghost" size="sm"><Link to={`/admin/exams/${t.id}`}>Open</Link></Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && <TableRow><TableCell colSpan={11} className="text-muted-foreground">No exams yet. Create one to get started.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
