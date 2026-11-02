import { useEffect, useState } from "react"
import { get } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const fmt = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "-")

export default function Exams() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/tests").then(setRows).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="grid gap-4">
      <h1 className="text-2xl font-semibold">Exams</h1>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {rows && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead><TableHead>Status</TableHead><TableHead>Starts</TableHead>
              <TableHead>Duration</TableHead><TableHead>Questions</TableHead><TableHead>Invited</TableHead><TableHead>Taken</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => (
              <TableRow key={t.id}>
                <TableCell className="font-medium">{t.title}</TableCell>
                <TableCell><Badge variant={t.status === "published" ? "default" : "secondary"}>{t.status}</Badge></TableCell>
                <TableCell>{fmt(t.starts_at)}</TableCell>
                <TableCell>{t.duration_min} min</TableCell>
                <TableCell>{t.question_count}</TableCell>
                <TableCell>{t.invited}</TableCell>
                <TableCell>{t.taken}</TableCell>
              </TableRow>
            ))}
            {!rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">No exams yet.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
