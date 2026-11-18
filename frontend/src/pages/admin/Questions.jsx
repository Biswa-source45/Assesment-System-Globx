import { useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Archive, CircleHelp, Pencil, Plus, Sparkles } from "lucide-react"
import { del } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useDebounced, usePaged } from "@/lib/usePaged"
import { useDepartments } from "@/lib/useDepartments"
import { useConfirm } from "@/components/ConfirmDialog"
import MoreRows from "@/components/MoreRows"
import { Loading } from "@/components/Spinner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export const TYPE_LABEL = {
  mcq_single: "MCQ (one answer)", mcq_multi: "MCQ (several answers)", short: "Short answer", long: "Explained answer", coding: "Coding", sql: "SQL",
}

export default function Questions() {
  const confirm = useConfirm()
  const { departments, byId } = useDepartments()
  const author = useAuth().user.can.author  // other roles that may read the bank cannot change it
  const [type, setType] = useState("all")
  const [department, setDepartment] = useState("all")
  const [search, setSearch] = useState("")
  // the server filters and pages: 50 questions now, the next 50 when the list is scrolled to its end
  const paged = usePaged("/questions", { type: type === "all" ? "" : type, department_id: department === "all" ? "" : department, q: useDebounced(search.trim()) })
  const { rows } = paged

  async function archive(q) {
    const yes = await confirm({ title: "Archive this question?", description: `"${q.title}" disappears from the bank. Exams that already use it keep working.`, action: "Archive", destructive: true })
    if (!yes) return
    try { await del(`/questions/${q.id}`); toast.success("Archived"); paged.reload() } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Question bank</h1>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline"><Link to="/admin/help?topic=question-types"><CircleHelp /> Question help</Link></Button>
          {author && <Button asChild variant="outline"><Link to="/admin/questions/new?ai=1"><Sparkles /> Create with AI</Link></Button>}
          {author && <Button asChild><Link to="/admin/questions/new"><Plus /> New question</Link></Button>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Search by title" aria-label="Search questions" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Select value={department} onValueChange={setDepartment}>
          <SelectTrigger className="w-52" aria-label="Filter by department"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All departments</SelectItem>
            {(departments ?? []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={type} onValueChange={setType}>
          <SelectTrigger className="w-52" aria-label="Filter by type"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      {paged.error && !rows && <p className="text-sm text-destructive">{paged.error}</p>}
      {rows === null && !paged.error && <Loading />}
      {rows && (
        <Table>
          <TableHeader>
            <TableRow><TableHead>Title</TableHead><TableHead>Department</TableHead><TableHead>Type</TableHead><TableHead>Difficulty</TableHead><TableHead>Marks</TableHead><TableHead>Cases</TableHead><TableHead /></TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((q) => (
              <TableRow key={q.id}>
                <TableCell className="font-medium">{author ? <Link className="hover:underline" to={`/admin/questions/${q.id}`}>{q.title}</Link> : q.title}</TableCell>
                <TableCell>{byId[q.department_id]?.name ?? "-"}</TableCell>
                <TableCell><Badge variant="secondary">{TYPE_LABEL[q.type] ?? q.type}</Badge></TableCell>
                <TableCell>{q.difficulty}</TableCell>
                <TableCell>{q.marks}</TableCell>
                <TableCell>{q.case_count || "-"}</TableCell>
                <TableCell className="text-right">
                  {author && <Button asChild variant="edit" size="sm"><Link to={`/admin/questions/${q.id}`}><Pencil /> Edit</Link></Button>}
                  {author && <Button variant="danger" size="sm" className="ml-2" onClick={() => archive(q)}><Archive /> Archive</Button>}
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">No questions found.</TableCell></TableRow>}
          </TableBody>
        </Table>
      )}
      <MoreRows paged={paged} what="questions" />
    </div>
  )
}
