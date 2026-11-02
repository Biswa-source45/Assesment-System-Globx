import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Plus, Shuffle, Sparkles, Trash2 } from "lucide-react"
import { del, get, post, put } from "@/lib/api"
import { useDepartments } from "@/lib/useDepartments"
import AutoPopulate from "@/pages/admin/AutoPopulate"
import QuestionPack from "@/pages/admin/QuestionPack"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { useConfirm } from "@/components/ConfirmDialog"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const needsReference = (q) => (q.type === "coding" || q.type === "sql") && !q.validated

// Pick questions from the bank for one section. Questions already in the exam are shown but cannot be picked again.
function QuestionPicker({ section, test, used, onClose, onAdded }) {
  const { departments } = useDepartments()
  const [department, setDepartment] = useState("any")
  const [rows, setRows] = useState(null)
  const [search, setSearch] = useState("")
  const [type, setType] = useState("all")
  const [picked, setPicked] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (section) setDepartment(test.department_id ?? "any") }, [section, test.department_id])  // starts with the exam's own department
  useEffect(() => {
    if (!section) return
    setPicked([])
    get("/questions?standalone=true" + (department === "any" ? "" : `&department_id=${department}`)).then(setRows).catch((e) => toast.error(e.message))
  }, [section, department])

  const shown = (rows ?? []).filter((q) => (type === "all" || q.type === type) && q.title.toLowerCase().includes(search.toLowerCase()))
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  async function add() {
    setBusy(true)
    try {
      let latest
      for (const id of picked) latest = await post(`/sections/${section.id}/items`, { kind: "question", question_id: id })
      onAdded(latest)
      onClose()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={!!section} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add questions to "{section?.title}"</DialogTitle>
          <DialogDescription>Choose from the question bank. Coding and SQL questions marked "Not validated" cannot be published until their solution passes every test case.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <Select value={department} onValueChange={setDepartment}>
            <SelectTrigger className="w-44" aria-label="Department filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="any">All departments</SelectItem>
              {(departments ?? []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input aria-label="Search the bank" placeholder="Search by title" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="w-48" aria-label="Question type filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              {Object.entries(TYPE_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="grid max-h-80 gap-1.5 overflow-auto">
          {rows === null && <p className="text-sm text-muted-foreground">Loading...</p>}
          {shown.map((q) => (
            <Label key={q.id} className="flex items-center gap-3 rounded-md border p-2 font-normal has-[[data-disabled]]:opacity-50">
              <Checkbox checked={picked.includes(q.id) || used.has(q.id)} disabled={used.has(q.id)} onCheckedChange={() => toggle(q.id)} />
              <span className="grow">{q.title}</span>
              {used.has(q.id) && <span className="text-xs text-muted-foreground">already in this exam</span>}
              {needsReference(q) && <Badge className="bg-destructive text-white">Not validated</Badge>}
              <Badge variant="secondary">{TYPE_LABEL[q.type] ?? q.type}</Badge>
              <span className="w-14 text-right text-xs text-muted-foreground">{q.marks} marks</span>
            </Label>
          ))}
          {rows && !shown.length && <p className="text-sm text-muted-foreground">No questions found.</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!picked.length || busy} onClick={add}>{busy ? "Adding..." : `Add ${picked.length || ""} selected`}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function itemTitle(it) {
  if (it.question) return it.question.title
  if (it.kind === "group") return `${it.group?.title ?? "Linked set"} (linked set, ${it.group?.count ?? "?"} questions)`
  return `Random pool: ${it.pool?.draw ?? "?"} questions`
}

function SectionCard({ section, test, setTest, locked, onPick, onPopulate }) {
  const confirm = useConfirm()
  const [title, setTitle] = useState(section.title)
  const [timer, setTimer] = useState(section.timer_min ?? "")

  async function saveHeader() {
    const body = {
      title: title.trim() || section.title, timer_min: timer === "" ? null : Number(timer), shuffle: section.shuffle, lock_nav: section.lock_nav,
      min_score: section.min_score, allow_negative: section.allow_negative,
    }
    if (body.title === section.title && body.timer_min === (section.timer_min ?? null)) return
    try { setTest(await put(`/sections/${section.id}`, body)) } catch (e) { toast.error(e.message) }
  }
  async function removeSection() {
    const yes = await confirm({ title: "Remove this section?", description: `"${section.title}" and the ${section.items.length} questions in it are removed from this exam. The questions stay in the bank.`, action: "Remove section", destructive: true })
    if (!yes) return
    try { setTest(await del(`/sections/${section.id}`)) } catch (e) { toast.error(e.message) }
  }
  async function removeItem(it) {
    const yes = await confirm({ title: "Remove this question?", description: `"${itemTitle(it)}" is removed from this section. It stays in the bank.`, action: "Remove", destructive: true })
    if (!yes) return
    try { setTest(await del(`/items/${it.id}`)) } catch (e) { toast.error(e.message) }
  }

  return (
    <Card data-testid="exam-section">
      <CardContent className="grid gap-3 pt-6">
        <div className="flex flex-wrap items-center gap-2">
          <Input className="min-w-48 flex-1 font-medium" aria-label={`Section ${section.order + 1} title`} value={title} disabled={locked}
            onChange={(e) => setTitle(e.target.value)} onBlur={saveHeader} />
          <Input className="w-40" type="number" min="1" placeholder="Timer (min)" aria-label={`Section ${section.order + 1} timer in minutes`} value={timer} disabled={locked}
            onChange={(e) => setTimer(e.target.value)} onBlur={saveHeader} />
          <span className="text-sm text-muted-foreground">{section.question_count} questions, {section.marks} marks</span>
          {!locked && <Button variant="ghost" size="icon" aria-label={`Remove section ${section.title}`} onClick={removeSection}><Trash2 /></Button>}
        </div>
        {section.items.map((it) => (
          <div key={it.id} className="flex items-center gap-2 rounded-md border p-2 text-sm" data-testid="exam-item">
            <span className="grow">{itemTitle(it)}</span>
            {it.question && needsReference(it.question) && <Badge className="bg-destructive text-white">Not validated</Badge>}
            {it.question && <Badge variant="secondary">{TYPE_LABEL[it.question.type] ?? it.question.type}</Badge>}
            {it.question && <span className="w-16 text-right text-xs text-muted-foreground">{it.question.marks} marks</span>}
            {!locked && <Button variant="ghost" size="icon" className="size-8" aria-label={`Remove ${itemTitle(it)}`} onClick={() => removeItem(it)}><Trash2 /></Button>}
          </div>
        ))}
        {!section.items.length && <p className="text-sm text-muted-foreground">No questions yet.</p>}
        {!locked && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => onPick(section)}><Plus /> Add questions</Button>
            <Button variant="outline" size="sm" onClick={() => onPopulate(section)}><Shuffle /> Auto populate</Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function ExamQuestions({ test, setTest }) {
  const locked = test.status !== "draft"
  const [newTitle, setNewTitle] = useState("")
  const [pickFor, setPickFor] = useState(null)
  const [populateFor, setPopulateFor] = useState(null)
  const [packOpen, setPackOpen] = useState(false)
  const used = new Set(test.sections.flatMap((s) => s.items.map((i) => i.question?.id).filter(Boolean)))

  async function addSection(e) {
    e.preventDefault()
    try {
      setTest(await post(`/tests/${test.id}/sections`, { title: newTitle.trim() || `Section ${test.sections.length + 1}` }))
      setNewTitle("")
    } catch (err) {
      toast.error(err.message)
    }
  }

  return (
    <div className="grid max-w-3xl gap-4">
      {locked && <Alert className="p-3">This exam is published, so its sections and questions are frozen. Unpublish it to change them.</Alert>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground" data-testid="exam-totals">{test.question_count} questions, {test.total_marks} marks in total</p>
        {!locked && <Button variant="outline" size="sm" onClick={() => setPackOpen(true)}><Sparkles /> Build with AI</Button>}
      </div>
      {test.sections.map((s) => <SectionCard key={s.id} section={s} test={test} setTest={setTest} locked={locked} onPick={setPickFor} onPopulate={setPopulateFor} />)}
      {!locked && (
        <form onSubmit={addSection} className="flex gap-2">
          <Input aria-label="New section title" placeholder={`Section ${test.sections.length + 1}`} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
          <Button type="submit" variant="outline"><Plus /> Add section</Button>
        </form>
      )}
      <QuestionPicker section={pickFor} test={test} used={used} onClose={() => setPickFor(null)} onAdded={setTest} />
      {populateFor && <AutoPopulate test={test} section={populateFor} onClose={() => setPopulateFor(null)} onAdded={setTest} />}
      {packOpen && <QuestionPack test={test} onClose={() => setPackOpen(false)} onImported={setTest} />}
    </div>
  )
}
