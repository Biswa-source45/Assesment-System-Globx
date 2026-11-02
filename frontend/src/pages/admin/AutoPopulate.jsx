import { useState } from "react"
import { toast } from "sonner"
import { Shuffle, X } from "lucide-react"
import { post } from "@/lib/api"
import { useDepartments } from "@/lib/useDepartments"
import { TYPE_LABEL } from "@/pages/admin/Questions"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const LEVELS = [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]]

// Fill a section with random questions from the bank. The server picks and nothing is saved until the admin has looked at the
// pick (removed some, or picked again) and presses Add. Questions already in the exam are never picked again.
export default function AutoPopulate({ test, section, onClose, onAdded }) {
  const { departments } = useDepartments()
  const [department, setDepartment] = useState(test.department_id ?? "any")
  const [types, setTypes] = useState(null)  // null: every type the department offers
  const [mix, setMix] = useState({ easy: 2, medium: 2, hard: 1 })
  const [skills, setSkills] = useState("")
  const [pick, setPick] = useState(null)    // { questions, short } as the server returned it
  const [busy, setBusy] = useState(false)

  const dept = departments?.find((d) => d.id === department)
  const offered = dept ? dept.question_types : Object.keys(TYPE_LABEL)
  const chosen = types ?? offered
  const total = LEVELS.reduce((n, [k]) => n + (Number(mix[k]) || 0), 0)

  const changeDepartment = (v) => { setDepartment(v); setTypes(null); setPick(null) }
  const toggleType = (t) => { setTypes(chosen.includes(t) ? chosen.filter((x) => x !== t) : [...chosen, t]); setPick(null) }

  async function choose() {
    setBusy(true)
    try {
      setPick(await post(`/tests/${test.id}/auto-populate`, {
        department_id: department === "any" ? null : department, types: chosen,
        easy: Number(mix.easy) || 0, medium: Number(mix.medium) || 0, hard: Number(mix.hard) || 0,
        skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
      }))
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function add() {
    setBusy(true)
    try {
      let latest
      for (const q of pick.questions) latest = await post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
      onAdded(latest)
      toast.success(`${pick.questions.length} questions added to ${section.title}`)
      onClose()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const shortText = pick && Object.entries(pick.short).map(([level, n]) => `${n} more ${level}`).join(", ")
  const marks = pick?.questions.reduce((n, q) => n + q.marks, 0) ?? 0

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Auto populate "{section.title}"</DialogTitle>
          <DialogDescription>Say what you need and the bank is searched at random. You can look at the pick, remove questions or pick again before anything is added.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label>Department</Label>
            <Select value={department} onValueChange={changeDepartment}>
              <SelectTrigger className="w-64" aria-label="Department to pick from"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any department</SelectItem>
                {(departments ?? []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>Question types</Label>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {offered.map((t) => (
                <Label key={t} className="flex items-center gap-2 font-normal"><Checkbox checked={chosen.includes(t)} onCheckedChange={() => toggleType(t)} /> {TYPE_LABEL[t]}</Label>
              ))}
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label>How many of each difficulty</Label>
            <div className="flex flex-wrap items-center gap-3">
              {LEVELS.map(([k, label]) => (
                <div key={k} className="flex items-center gap-2">
                  <Label htmlFor={`mix-${k}`} className="font-normal">{label}</Label>
                  <Input id={`mix-${k}`} className="w-20" type="number" min="0" max="50" value={mix[k]} onChange={(e) => { setMix({ ...mix, [k]: e.target.value }); setPick(null) }} />
                </div>
              ))}
              <span className="text-sm text-muted-foreground">{total} in total</span>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="pick-skills">Only questions tagged with (optional, comma separated)</Label>
            <Input id="pick-skills" placeholder="for example: numeracy, accounting" value={skills} onChange={(e) => { setSkills(e.target.value); setPick(null) }} />
          </div>

          {pick && (
            <div className="grid gap-2" data-testid="pick-result">
              {shortText && <Alert className="p-3" data-testid="pick-short">The bank could not supply everything you asked for: {shortText} question(s) are missing. Add more questions to the bank, or loosen the filters.</Alert>}
              {pick.questions.length === 0 && <p className="text-sm text-muted-foreground">No question matches these filters.</p>}
              {pick.questions.map((q) => (
                <div key={q.id} className="flex items-center gap-2 rounded-md border p-2 text-sm" data-testid="pick-row">
                  <span className="grow">{q.title}</span>
                  <Badge variant="secondary">{TYPE_LABEL[q.type] ?? q.type}</Badge>
                  <Badge variant="secondary">{q.difficulty}</Badge>
                  <span className="w-14 text-right text-xs text-muted-foreground">{q.marks} marks</span>
                  <Button variant="ghost" size="icon" className="size-7" aria-label={`Leave out ${q.title}`} onClick={() => setPick({ ...pick, questions: pick.questions.filter((x) => x.id !== q.id) })}><X /></Button>
                </div>
              ))}
              {pick.questions.length > 0 && <p className="text-xs text-muted-foreground">{pick.questions.length} questions, {marks} marks</p>}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant={pick ? "outline" : "default"} disabled={busy || total < 1 || total > 50 || !chosen.length} onClick={choose}><Shuffle /> {pick ? "Pick again" : "Pick questions"}</Button>
          {pick?.questions.length > 0 && <Button disabled={busy} onClick={add}>{busy ? "Adding..." : `Add ${pick.questions.length} questions`}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
