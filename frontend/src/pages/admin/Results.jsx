import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate, RESULT_STATE } from "@/lib/labels"
import { STATE_TONE, TONE } from "@/lib/verdict"
import { useDepartments } from "@/lib/useDepartments"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

// One line per published exam: where its results stand. The Super Admin also sees the archived exams here, with their results.
export default function Results() {
  const { byId } = useDepartments()
  const { user } = useAuth()
  const [rows, setRows] = useState(null)

  useEffect(() => {
    Promise.all([get("/tests"), user.can.super ? get("/tests?archived=true") : []])
      .then(([list, old]) => Promise.all([...list.filter((t) => t.status === "published"), ...old].map(async (t) => ({ ...t, results: await get(`/tests/${t.id}/results`) }))))
      .then(setRows)
      .catch((e) => toast.error(e.message))
  }, [user.can.super])

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Results</h1>
        <p className="text-sm text-muted-foreground">Results are calculated for the whole exam after its end time, reviewed here, then declared to the candidates.</p>
      </div>
      <Table>
        <TableHeader>
          <TableRow><TableHead>Exam</TableHead><TableHead>Department</TableHead><TableHead>Closes</TableHead><TableHead>Results</TableHead><TableHead>Appeared</TableHead><TableHead>Need attention</TableHead><TableHead /></TableRow>
        </TableHeader>
        <TableBody>
          {rows?.map((t) => (
            <TableRow key={t.id} data-testid="results-exam">
              <TableCell className="font-medium"><Link className="hover:underline" to={`/admin/results/${t.id}`}>{t.title}</Link>{t.status === "archived" && <Badge variant="secondary" className="ml-2" data-testid="archived-badge">Archived</Badge>}</TableCell>
              <TableCell>{byId[t.department_id]?.name ?? "-"}</TableCell>
              <TableCell>{t.ends_at ? fmtDate(t.ends_at) : "No end time"}</TableCell>
              <TableCell><Badge variant="outline" className={TONE[STATE_TONE[t.results.state]]}>{RESULT_STATE[t.results.state]}</Badge></TableCell>
              <TableCell>{t.results.summary.appeared} of {t.results.summary.assigned}</TableCell>
              <TableCell>{t.results.attention || "-"}</TableCell>
              <TableCell className="text-right"><Button asChild size="sm"><Link to={`/admin/results/${t.id}`}>Open</Link></Button></TableCell>
            </TableRow>
          ))}
          {rows && !rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">No published exams yet.</TableCell></TableRow>}
          {!rows && <TableRow><TableCell colSpan={7} className="text-muted-foreground">Loading...</TableCell></TableRow>}
        </TableBody>
      </Table>
    </div>
  )
}
