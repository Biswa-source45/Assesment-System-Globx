import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Plus } from "lucide-react"
import { get } from "@/lib/api"
import { fmtDate } from "@/lib/labels"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export default function Exams() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/tests").then(setRows).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Exams</h1>
        <Button asChild><Link to="/admin/exams/new"><Plus /> New exam</Link></Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead><TableHead>Status</TableHead><TableHead>Opens</TableHead><TableHead>Time</TableHead>
              <TableHead>Questions</TableHead><TableHead>Marks</TableHead><TableHead>Invited</TableHead><TableHead>Taken</TableHead><TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="font-medium"><Link className="hover:underline" to={`/admin/exams/${t.id}`}>{t.title}</Link></TableCell>
                <TableCell><Badge variant={t.status === "published" ? "default" : "secondary"}>{t.status}</Badge></TableCell>
                <TableCell>{fmtDate(t.starts_at)}</TableCell>
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
            {!rows.length && <TableRow><TableCell colSpan={9} className="text-muted-foreground">No exams yet. Create one to get started.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
