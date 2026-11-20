import { useState } from "react"
import { toast } from "sonner"
import { MoreHorizontal } from "lucide-react"
import { get, post, put } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate } from "@/lib/labels"
import { useConfirm } from "@/components/ConfirmDialog"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
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
  edit: { label: "Edit details" },
  email: { label: "Email login" },
  mails: { label: "Mail details" },
}
const OWN_DIALOG = ["password", "edit", "mails"]  // these have a dialog of their own below

// What an admin can do with a participant depends on where they are in the exam.
function available(status, assignmentStatus) {
  if (status === "in_progress") return ["extend", "terminate", "password"]
  if (["cancelled", "expired"].includes(assignmentStatus)) return ["reset"]
  if (assignmentStatus === "invited") return ["extend", "password", "cancel"]
  return ["reset", "password"]  // finished or locked
}

// On the participants list a person can also be corrected and mailed; Email login needs a published exam, an email, and a person who has not started.
function participantActions(row) {
  if (!row.participant || !row.mail) return []
  return ["edit", ...(row.published && row.assignmentStatus === "invited" && row.email ? ["email"] : []), "mails"]
}

// row: { id, name, username, status, assignmentStatus } and, on the participants list, { participant, email, published, mail }. onDone runs after anything
// changed, so the page can reload; onSheet gets a login that was just made (a new password is shown only once).
function Actions({ row, onDone, onSheet }) {
  const confirm = useConfirm()
  const [dialog, setDialog] = useState(null)  // { kind } or { kind: "password", password } or { kind: "mails", history }
  const [form, setForm] = useState({ name: "", email: "" })
  const [error, setError] = useState("")
  const [minutes, setMinutes] = useState(10)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const close = () => { setDialog(null); setReason(""); setMinutes(10) }

  async function emailLogin() {
    const yes = await confirm({ title: `Email the login to ${row.name}?`, description: `A new password is made and mailed to ${row.email}, with the exam details. The earlier password stops working.`, action: "Send login" })
    if (!yes) return
    try {
      const out = await post(`/assignments/${row.id}/send-login`)
      onSheet?.(out.participant)
      toast.success(`Login mailed to ${row.email}. The new password is on the sheet at the top of this page.`)
      onDone?.()
    } catch (e) { toast.error(e.message) }
  }

  async function saveEdit(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const out = await put(`/assignments/${row.id}/participant`, { name: form.name, email: form.email })
      const moved = row.email && out.email.toLowerCase() !== row.email.toLowerCase() && ["sent", "queued", "failed", "email_changed"].includes(row.mail?.state)
      toast.success(moved ? "Saved. No email was sent: the login went to the old address. Use Email login to send it to the new one." : "Saved. No email was sent.")
      close()
      onDone?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function choose(kind) {
    if (kind === "email") return emailLogin()
    if (kind === "edit") { setForm({ name: row.name, email: row.email }); setError(""); return setDialog({ kind }) }
    if (kind === "mails") {
      try { return setDialog({ kind, history: await get(`/assignments/${row.id}/login-mails`) }) } catch (e) { return toast.error(e.message) }
    }
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
          {[...participantActions(row), ...available(row.status, row.assignmentStatus)].map((k) => <DropdownMenuItem key={k} onSelect={() => choose(k)}>{ACTIONS[k].label}</DropdownMenuItem>)}
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

      <Dialog open={dialog?.kind === "edit"} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <form onSubmit={saveEdit} className="grid gap-4">
            <DialogHeader><DialogTitle>Edit details: {row.name}</DialogTitle>
              <DialogDescription>Correct the name or the email. The username ({row.username}) and the password stay as they are. Saving does not send any email.</DialogDescription></DialogHeader>
            <div className="grid gap-1.5"><Label htmlFor="edit-name">Full name</Label><Input id="edit-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="grid gap-1.5"><Label htmlFor="edit-email">Email</Label><Input id="edit-email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>Back</Button>
              <Button type="submit" disabled={busy} loading={busy}>{busy ? "Saving..." : "Save"}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={dialog?.kind === "mails"} onOpenChange={(o) => !o && close()}>
        <DialogContent>
          <DialogHeader><DialogTitle>Login mails: {row.name}</DialogTitle>
            <DialogDescription>Email now: {dialog?.history?.email || "none"}. Sent means the mail server accepted the mail; a mail that bounces later cannot be seen here.</DialogDescription></DialogHeader>
          <div className="grid max-h-80 gap-2 overflow-y-auto" data-testid="mail-history">
            {dialog?.history?.mails.map((m, i) => (
              <div key={i} className="grid gap-0.5 rounded-md border p-3 text-sm">
                <div className="flex items-center justify-between gap-2"><span className="font-medium">{m.to}</span>
                  <Badge variant={m.status === "failed" ? "destructive" : "secondary"}>{m.status === "sent" ? "Sent" : m.status === "queued" ? "Sending" : "Not delivered"}</Badge></div>
                <span className="text-xs text-muted-foreground">Queued {fmtDate(m.queued_at)}{m.sent_at ? `, sent ${fmtDate(m.sent_at)}` : ""}</span>
                {m.error && <span className="text-xs text-destructive">{m.error}</span>}
              </div>
            ))}
            {dialog?.history && !dialog.history.mails.length && <p className="text-sm text-muted-foreground">No login mail has been sent to this person yet.</p>}
          </div>
          <DialogFooter><Button onClick={close}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!a && !OWN_DIALOG.includes(dialog.kind)} onOpenChange={(o) => !o && close()}>
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
              <Button type="submit" disabled={busy} loading={busy}>{busy ? "Working..." : a?.button}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

// Only people who may manage participants get the menu; the server refuses everyone else anyway.
export default function AssignmentActions(props) {
  const { user } = useAuth()
  return user.can.recruit ? <Actions {...props} /> : null
}
