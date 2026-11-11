import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Download, Printer } from "lucide-react"
import { get, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { STATUS } from "@/lib/labels"
import { useConfirm } from "@/components/ConfirmDialog"
import AssignmentActions from "@/components/AssignmentActions"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

function downloadCsv(list, title) {
  const cell = (v) => `"${String(v).replace(/"/g, '""')}"`
  const text = ["Name,Username,Password", ...list.map((p) => [p.name, p.username, p.password].map(cell).join(","))].join("\r\n")
  const a = document.createElement("a")
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }))
  a.download = `${title.replace(/[^A-Za-z0-9]+/g, "-")}-logins.csv`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

// A person who appears again (a new password) replaces their earlier line; everyone else stays.
const merge = (old, add) => [...(old ?? []).filter((o) => !add.some((n) => n.assignment_id === o.assignment_id)), ...add]

export default function ExamParticipants({ test }) {
  const recruit = useAuth().user.can.recruit  // others may only look at the list
  const confirm = useConfirm()
  const [names, setNames] = useState("")
  const [created, setCreated] = useState(null)  // the only time the passwords are visible
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    get(`/tests/${test.id}/candidates`).then((d) => setRows(d.rows)).catch((e) => toast.error(e.message))
  }, [test.id])
  useEffect(() => { load() }, [load])

  async function create(e) {
    e.preventDefault()
    const list = names.split("\n").map((s) => s.trim()).filter(Boolean)
    const yes = await confirm({ title: `Create ${list.length} ${list.length === 1 ? "login" : "logins"}?`, description: "Each person gets a username and a password. The passwords are shown once, so download the sheet before you leave this page.", action: "Create" })
    if (!yes) return
    setBusy(true)
    try {
      const out = await post(`/tests/${test.id}/participants`, { names: list })
      setCreated((old) => merge(old, out.participants))  // keep the earlier logins on the sheet: passwords cannot be shown again
      setNames("")
      load()
    } catch (err) {
      toast.error(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function freshSheet() {
    const yes = await confirm({ title: "Get a fresh login sheet?", description: "Everyone who has not started the exam gets a new password and their old one stops working. People who are taking the exam now, or have finished, keep theirs.", action: "Get new passwords" })
    if (!yes) return
    try {
      const out = await post(`/tests/${test.id}/passwords`)
      setCreated((old) => merge(old, out.participants))
      toast.success(out.participants.length ? `${out.participants.length} new password(s) are on the sheet above` : "Nobody is waiting to start")
    } catch (err) {
      toast.error(err.message)
    }
  }

  return (
    <div className="grid max-w-4xl gap-4">
      {recruit && <Card>
        <CardHeader>
          <CardTitle>Add participants</CardTitle>
          <CardDescription>One person per line: the name, or the name and email separated by a comma (email is optional). Each person gets their own username and password for this exam.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="grid gap-3">
            <Label htmlFor="names" className="sr-only">Participant names</Label>
            <Textarea id="names" className="min-h-28" placeholder={"Asha Rao\nVikram Das, vikram@example.com"} value={names} onChange={(e) => setNames(e.target.value)} />
            <div><Button type="submit" disabled={busy || !names.trim()}>{busy ? "Creating..." : "Create logins"}</Button></div>
          </form>
        </CardContent>
      </Card>}

      {created && (
        <Card className="print-area" data-testid="credentials">
          <CardHeader>
            <CardTitle>Logins for {test.title}</CardTitle>
            <CardDescription>Sign in at {window.location.origin}. Passwords are shown only on this page, so this list keeps every login you create here. Print or download it before you leave. Lost one? Use New password for a person, or Get a fresh login sheet for everyone who has not started.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Table>
              <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Username</TableHead><TableHead>Password</TableHead></TableRow></TableHeader>
              <TableBody>
                {created.map((p) => (
                  <TableRow key={p.assignment_id}>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="font-mono" data-testid="cred-username">{p.username}</TableCell>
                    <TableCell className="font-mono" data-testid="cred-password">{p.password}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex gap-2 print:hidden">
              <Button variant="outline" size="sm" onClick={() => window.print()}><Printer /> Print</Button>
              <Button variant="outline" size="sm" onClick={() => downloadCsv(created, test.title)}><Download /> Download all ({created.length}) as CSV</Button>
              <Button variant="ghost" size="sm" onClick={() => setCreated(null)}>Hide passwords</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>Participants</CardTitle>
            {recruit && <Button variant="outline" size="sm" onClick={freshSheet}>Get a fresh login sheet</Button>}
          </div>
        </CardHeader>
        <CardContent>
          {rows && (
            <Table>
              <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Username</TableHead><TableHead>Status</TableHead><TableHead>Score</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.assignment_id}>
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className="font-mono text-xs">{r.username || r.email}</TableCell>
                    <TableCell><Badge variant={r.status === "banned" ? "destructive" : "secondary"}>{STATUS[r.status] ?? r.status}</Badge></TableCell>
                    <TableCell>{r.score != null ? `${r.score} / ${r.max}` : "-"}</TableCell>
                    <TableCell className="text-right">
                      <AssignmentActions row={{ id: r.assignment_id, name: r.name, username: r.username || r.email, status: r.status, assignmentStatus: r.status }} onDone={load} />
                    </TableCell>
                  </TableRow>
                ))}
                {!rows.length && <TableRow><TableCell colSpan={5} className="text-muted-foreground">Nobody yet.</TableCell></TableRow>}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
