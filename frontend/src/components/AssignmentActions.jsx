import { useState } from "react"
import { toast } from "sonner"
import { MoreHorizontal } from "lucide-react"
import { post } from "@/lib/api"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

const ACTIONS = {
  extend: { label: "Extend time", help: "Adds minutes to this candidate's time.", button: "Extend", minutes: true, reason: true },
  terminate: { label: "End exam now", help: "Submits what the candidate has answered so far and ends the exam. This cannot be undone.", button: "End exam", reason: true },
  reset: { label: "Re-open exam", help: "Discards the previous attempt so the candidate can start from the beginning. Use it after a technical problem or an unfair lock.", button: "Re-open", reason: true },
  cancel: { label: "Cancel invitation", help: "The candidate can no longer start this exam.", button: "Cancel invitation", reason: false },
  password: { label: "New password" },
}

// What an admin can do with a participant depends on where they are in the exam.
function available(status, assignmentStatus) {
  if (status === "in_progress") return ["extend", "terminate", "password"]
  if (["cancelled", "expired"].includes(assignmentStatus)) return ["reset"]
  if (assignmentStatus === "invited") return ["extend", "password", "cancel"]
  return ["reset", "password"]  // finished or locked
}

// row: { id, name, username, status, assignmentStatus }. onDone runs after anything changed, so the page can reload.
export default function AssignmentActions({ row, onDone }) {
  const [dialog, setDialog] = useState(null)  // { kind } or { kind: "password", password }
  const [minutes, setMinutes] = useState(10)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const close = () => { setDialog(null); setReason(""); setMinutes(10) }

  async function choose(kind) {
    if (kind !== "password") return setDialog({ kind })
    try {
      const out = await post(`/assignments/${row.id}/password`)
      setDialog({ kind, password: out.password })
      onDone?.()
    } catch (e) { toast.error(e.message) }
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await post(`/assignments/${row.id}/action`, { action: dialog.kind, minutes: Number(minutes), reason })
      toast.success(`${ACTIONS[dialog.kind].label}: done for ${row.name}`)
      close()
      onDone?.()
    } catch (err) {
      toast.error(err.message)
    } finally {
      setBusy(false)
    }
  }

  const a = dialog && ACTIONS[dialog.kind]
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label={`Actions for ${row.name}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {available(row.status, row.assignmentStatus).map((k) => <DropdownMenuItem key={k} onSelect={() => choose(k)}>{ACTIONS[k].label}</DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={dialog?.kind === "password"} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <DialogHeader><DialogTitle>New password for {row.name}</DialogTitle><DialogDescription>Shown only now. Give it to the candidate; the old password no longer works.</DialogDescription></DialogHeader>
          <div className="grid gap-1 rounded-md bg-muted p-3 font-mono text-sm">
            <span>Username: {row.username}</span><span data-testid="new-password">Password: {dialog?.password}</span>
          </div>
          <DialogFooter><Button onClick={close}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!a && dialog.kind !== "password"} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <form onSubmit={submit} className="grid gap-4">
            <DialogHeader><DialogTitle>{a?.label}: {row.name}</DialogTitle><DialogDescription>{a?.help}</DialogDescription></DialogHeader>
            {a?.minutes && (
              <div className="grid gap-1.5"><Label htmlFor="act-minutes">Minutes to add</Label><Input id="act-minutes" type="number" min="1" max="240" required value={minutes} onChange={(e) => setMinutes(e.target.value)} /></div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="act-reason">Reason{a?.reason ? "" : " (optional)"}</Label>
              <Textarea id="act-reason" required={a?.reason} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Kept in the audit log" />
            </div>
            {dialog?.kind === "terminate" && <Alert variant="destructive" className="p-3">The candidate's screen will end within a few seconds.</Alert>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>Back</Button>
              <Button type="submit" disabled={busy}>{busy ? "Working..." : a?.button}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
