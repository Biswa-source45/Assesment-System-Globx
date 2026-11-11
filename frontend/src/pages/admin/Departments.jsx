import { useState } from "react"
import { toast } from "sonner"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { del, post, put } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useDepartments } from "@/lib/useDepartments"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { useConfirm } from "@/components/ConfirmDialog"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const ALL_TYPES = Object.keys(TYPE_LABEL)

// Create or edit a department: its name and the question types its authors can use.
function DepartmentDialog({ target, onClose, onSaved }) {
  const editing = target && target !== "new" ? target : null
  const [name, setName] = useState(editing?.name ?? "")
  const [types, setTypes] = useState(editing?.question_types ?? ["mcq_single", "mcq_multi", "short", "long"])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const toggle = (t) => setTypes((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const body = { name, question_types: types }
      editing ? await put(`/departments/${editing.id}`, body) : await post("/departments", body)
      toast.success(editing ? "Department saved" : "Department created")
      onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.name}` : "New department"}</DialogTitle>
            <DialogDescription>The department decides which kinds of questions authors can create for it.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5"><Label htmlFor="dep-name">Name</Label><Input id="dep-name" required value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="grid gap-2">
            <Label>Question types</Label>
            {ALL_TYPES.map((t) => (
              <Label key={t} className="flex items-center gap-2 font-normal"><Checkbox checked={types.includes(t)} onCheckedChange={() => toggle(t)} /> {TYPE_LABEL[t]}</Label>
            ))}
          </div>
          {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || !types.length}>{busy ? "Saving..." : editing ? "Save department" : "Create department"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function Departments() {
  const confirm = useConfirm()
  const author = useAuth().user.can.author
  const { departments, reload } = useDepartments()
  const [target, setTarget] = useState(null)  // "new", a department being edited, or null

  async function remove(d) {
    const yes = await confirm({ title: `Delete ${d.name}?`, description: "A department can be deleted only when no question or exam uses it.", action: "Delete", destructive: true })
    if (!yes) return
    try { await del(`/departments/${d.id}`); toast.success("Department deleted"); reload() } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Departments</h1>
          <p className="text-sm text-muted-foreground">Each exam and each question belongs to a department. The department decides which question types its authors can use.</p>
        </div>
        {author && <Button onClick={() => setTarget("new")}><Plus /> New department</Button>}
      </div>
      {departments && (
        <Table>
          <TableHeader><TableRow><TableHead>Department</TableHead><TableHead>Question types</TableHead><TableHead>Questions</TableHead><TableHead>Exams</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {departments.map((d) => (
              <TableRow key={d.id} data-testid="department-row">
                <TableCell className="font-medium">{d.name}</TableCell>
                <TableCell><div className="flex flex-wrap gap-1">{d.question_types.map((t) => <Badge key={t} variant="secondary">{TYPE_LABEL[t] ?? t}</Badge>)}</div></TableCell>
                <TableCell>{d.questions}</TableCell>
                <TableCell>{d.exams}</TableCell>
                <TableCell className="text-right">
                  {author && <Button variant="edit" size="icon" aria-label={`Edit ${d.name}`} title="Edit" onClick={() => setTarget(d)}><Pencil /></Button>}
                  {author && <Button variant="danger" size="icon" className="ml-1" aria-label={`Delete ${d.name}`} title="Delete" onClick={() => remove(d)}><Trash2 /></Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {target && <DepartmentDialog key={target === "new" ? "new" : target.id} target={target} onClose={() => setTarget(null)} onSaved={reload} />}
    </div>
  )
}
