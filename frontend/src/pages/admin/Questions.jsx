import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Plus } from "lucide-react"
import { del, get } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const TYPE_LABEL = {
  mcq_single: "MCQ (one answer)", mcq_multi: "MCQ (several answers)", short: "Short answer", long: "Explained answer", coding: "Coding", sql: "SQL",
}

export default function Questions() {
  const [rows, setRows] = useState(null)
  const [type, setType] = useState("all")
  const [search, setSearch] = useState("")
  const [error, setError] = useState("")

  const load = useCallback(() => {
    get("/questions" + (type === "all" ? "" : `?type=${type}`)).then(setRows).catch((e) => setError(e.message))
  }, [type])
  useEffect(load, [load])

  async function archive(q) {
    if (!confirm(`Archive "${q.title}"? It disappears from the bank but exams that already use it keep working.`)) return
    try { await del(`/questions/${q.id}`); toast.success("Archived"); load() } catch (e) { toast.error(e.message) }
  }

  const shown = rows?.filter((r) => r.title.toLowerCase().includes(search.toLowerCase()))
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Question bank</h1>
        <Button asChild><Link to="/admin/questions/new"><Plus /> New question</Link></Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Search by title" aria-label="Search questions" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-52" aria-label="Filter by type"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {shown && (
        <Table>
          <TableHeader>
            <TableRow><TableHead>Title</TableHead><TableHead>Type</TableHead><TableHead>Difficulty</TableHead><TableHead>Marks</TableHead><TableHead>Cases</TableHead><TableHead /></TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((q) => (
              <TableRow key={q.id}>
                <TableCell className="font-medium"><Link className="hover:underline" to={`/admin/questions/${q.id}`}>{q.title}</Link></TableCell>
                <TableCell><Badge variant="secondary">{TYPE_LABEL[q.type] ?? q.type}</Badge></TableCell>
                <TableCell>{q.difficulty}</TableCell>
                <TableCell>{q.marks}</TableCell>
                <TableCell>{q.case_count || "-"}</TableCell>
                <TableCell className="text-right">
                  <Button asChild variant="ghost" size="sm"><Link to={`/admin/questions/${q.id}`}>Edit</Link></Button>
                  <Button variant="ghost" size="sm" onClick={() => archive(q)}>Archive</Button>
                </TableCell>
              </TableRow>
            ))}
            {!shown.length && <TableRow><TableCell colSpan={6} className="text-muted-foreground">No questions found.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
