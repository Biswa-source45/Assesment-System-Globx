import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { get } from "@/lib/api"
import { fmtDate, RESULT_STATE } from "@/lib/labels"
import { useDepartments } from "@/lib/useDepartments"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

// One line per published exam: where its results stand.
export default function Results() {
  const { byId } = useDepartments()
  const [rows, setRows] = useState(null)

  useEffect(() => {
    get("/tests")
      .then((list) => Promise.all(list.filter((t) => t.status === "published").map(async (t) => ({ ...t, results: await get(`/tests/${t.id}/results`) }))))
      .then(setRows)
      .catch((e) => toast.error(e.message))
  }, [])

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
              <TableCell className="font-medium"><Link className="hover:underline" to={`/admin/results/${t.id}`}>{t.title}</Link></TableCell>
              <TableCell>{byId[t.department_id]?.name ?? "-"}</TableCell>
              <TableCell>{t.ends_at ? fmtDate(t.ends_at) : "No end time"}</TableCell>
              <TableCell><Badge variant={t.results.state === "declared" ? "default" : t.results.state === "needs_attention" ? "destructive" : "secondary"}>{RESULT_STATE[t.results.state]}</Badge></TableCell>
              <TableCell>{t.results.summary.appeared} of {t.results.summary.assigned}</TableCell>
              <TableCell>{t.results.attention || "-"}</TableCell>
              <TableCell className="text-right"><Button asChild variant="ghost" size="sm"><Link to={`/admin/results/${t.id}`}>Open</Link></Button></TableCell>
            </TableRow>
          ))}
          {rows && !rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">No published exams yet.</TableCell></TableRow>}
          {!rows && <TableRow><TableCell colSpan={7} className="text-muted-foreground">Loading...</TableCell></TableRow>}
        </TableBody>
      </Table>
    </div>
  )
}
