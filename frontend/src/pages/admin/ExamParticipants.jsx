import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Download, Mail, Printer, Upload } from "lucide-react"
import { api, post } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate, STATUS } from "@/lib/labels"
import { useDebounced, usePaged } from "@/lib/usePaged"
import { useConfirm } from "@/components/ConfirmDialog"
import AssignmentActions from "@/components/AssignmentActions"
import MoreRows from "@/components/MoreRows"
import { Loading } from "@/components/Spinner"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import ParticipantBin from "@/pages/admin/ParticipantBin"

function saveFile(text, name) {
  const a = document.createElement("a")
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }))
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function downloadCsv(list, title) {
  const cell = (v) => `"${String(v).replace(/"/g, '""')}"`
  const text = ["Name,Username,Password", ...list.map((p) => [p.name, p.username, p.password].map(cell).join(","))].join("\r\n")
  saveFile(text, `${title.replace(/[^A-Za-z0-9]+/g, "-")}-logins.csv`)
}

// The sheet people fill in. The two sample rows use @example.com: the upload skips those, so an unchanged sample never creates anybody.
const SAMPLE_SHEET = "Full name,Email\r\nAsha Rao,asha.rao@example.com\r\nVikram Das,vikram.das@example.com\r\n"

// A person who appears again (a new password) replaces their earlier line; everyone else stays.
const merge = (old, add) => [...(old ?? []).filter((o) => !add.some((n) => n.assignment_id === o.assignment_id)), ...add]
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`
const hasEmail = (e) => !!e && !e.toLowerCase().endsWith("@exam.local")
const GREEN = "bg-emerald-100 text-emerald-800", AMBER = "bg-amber-100 text-amber-800"

// What is known about one person's login mail (the record kept for every mail: the address, the time, the reason when it did not go).
function MailCell({ mail }) {
  const small = "text-xs text-muted-foreground"
  if (!mail || mail.state === "no_email") return <span className={small}>No email</span>
  if (mail.state === "not_sent") return <Badge variant="outline">Not sent</Badge>
  if (mail.state === "queued") return <div className="grid gap-0.5"><Badge variant="secondary">Sending...</Badge><span className={small}>to {mail.to}</span></div>
  if (mail.state === "sent") return <div className="grid gap-0.5"><Badge className={GREEN}>Sent</Badge><span className={small}>to {mail.to}</span><span className={small}>{fmtDate(mail.at)}</span></div>
  if (mail.state === "password_changed") return <div className="grid max-w-60 gap-0.5"><Badge className={AMBER}>New password: not mailed</Badge><span className={small}>The mail to {mail.to} ({fmtDate(mail.at)}) holds an old password. Press Email login.</span></div>
  if (mail.state === "failed") return <div className="grid max-w-60 gap-0.5"><Badge variant="destructive">Not delivered</Badge><span className={small}>to {mail.to}</span><span className="text-xs text-destructive">{mail.error}</span></div>
  return (
    <div className="grid max-w-60 gap-0.5"><Badge className={AMBER}>Email changed: not sent</Badge>
      <span className={small}>The login went to {mail.to} ({fmtDate(mail.at)}). The new address has not been mailed.</span></div>
  )
}

export default function ExamParticipants({ test }) {
  const recruit = useAuth().user.can.recruit  // others may only look at the list
  const confirm = useConfirm()
  const published = test.status === "published"
  const [names, setNames] = useState("")
  const [created, setCreated] = useState(null)  // the only time the passwords are visible
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [formError, setFormError] = useState("")
  const [skipped, setSkipped] = useState([])  // rows of an uploaded sheet that could not be used, with the reason
  const [note, setNote] = useState(null)  // what the last "Send logins" did
  const [search, setSearch] = useState("")
  const [view, setView] = useState("list")  // "bin": the people deleted from this exam
  const fileRef = useRef(null)
  // 50 people now, the next 50 when the list is scrolled to its end; the server searches
  const paged = usePaged(`/tests/${test.id}/candidates`, { q: useDebounced(search.trim()) }, { idKey: "assignment_id" })
  const { rows } = paged
  const load = paged.reload
  const logins = paged.meta?.logins

  // Mails go out in the background: while some are still waiting, look again every few seconds so Sending... turns into Sent.
  useEffect(() => {
    if (!(logins?.queued > 0)) return
    const t = setTimeout(load, 5000)
    return () => clearTimeout(t)
  }, [logins, load])

  async function create(e) {
    e.preventDefault()
    const list = names.split("\n").map((s) => s.trim()).filter(Boolean)
    setFormError("")
    const yes = await confirm({ title: `Create ${list.length} ${list.length === 1 ? "login" : "logins"}?`, description: "Each person gets a username and a password. The passwords are shown once, so download the sheet before you leave this page. Nobody is e-mailed until you press Send logins by email.", action: "Create" })
    if (!yes) return
    setBusy(true)
    try {
      const out = await post(`/tests/${test.id}/participants`, { names: list, email_required: true })
      setCreated((old) => merge(old, out.participants))  // keep the earlier logins on the sheet: passwords cannot be shown again
      setNames("")
      setSkipped([])
      const known = out.participants.filter((p) => p.existing).length
      if (known) toast.info(`${plural(known, "person already had", "people already had")} a login: the same username, with a new password.`)
      load()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function readSheet(e) {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    setFormError("")
    setSkipped([])
    try {
      const form = new FormData()
      form.append("file", file)
      const out = await api(`/tests/${test.id}/participants/sheet`, { form })
      setNames((old) => [old.trim(), ...out.lines].filter(Boolean).join("\n"))
      setSkipped(out.problems)
      toast.success(`${plural(out.lines.length, "person", "people")} read from the sheet. Check the list, then press Create logins.`)
    } catch (err) {
      setFormError(err.message)
    }
  }

  async function freshSheet() {
    const yes = await confirm({ title: "Get a fresh login sheet?", description: "Everyone who has not started the exam gets a new password and their old one stops working. Nobody is e-mailed. People who are taking the exam now, or have finished, keep theirs.", action: "Get new passwords" })
    if (!yes) return
    try {
      const out = await post(`/tests/${test.id}/passwords`)
      setCreated((old) => merge(old, out.participants))
      toast.success(out.participants.length ? `${out.participants.length} new password(s) are on the sheet above` : "Nobody is waiting to start")
      load()  // their mailed passwords are out of date now: the list and the Send button must say so
    } catch (err) {
      toast.error(err.message)
    }
  }

  async function sendLogins(again) {
    const yes = await confirm({
      title: again ? "Send logins to everyone again?" : `Send logins to ${plural(logins?.waiting ?? 0, "person", "people")}?`,
      description: again
        ? "Everyone who has not started the exam and has an email gets a new password by e-mail. Passwords mailed before stop working."
        : "Each person gets a new password by e-mail, with the exam details and a link that opens the login page. A password they were given before stops working. People who were already mailed are left alone.",
      action: "Send logins",
    })
    if (!yes) return
    setSending(true)
    setNote(null)
    try {
      const out = await post(`/tests/${test.id}/send-logins`, { again })
      setCreated((old) => merge(old, out.participants))  // the same logins, kept on the sheet in case a mail does not arrive
      setNote(out)
      load()
    } catch (err) {
      toast.error(err.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="grid max-w-5xl gap-4">
      {recruit && <Card>
        <CardHeader>
          <CardTitle>Add participants</CardTitle>
          <CardDescription>One person per line: the full name, then the email after a comma. Each person gets their own username and password for this exam. Or upload a sheet with the columns Full name and Email.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="grid gap-3">
            <Label htmlFor="names" className="sr-only">Participant names</Label>
            <Textarea id="names" className="min-h-28" placeholder={"Asha Rao, asha.rao@gmail.com\nVikram Das, vikram.das@gmail.com"} value={names} onChange={(e) => setNames(e.target.value)} />
            {formError && <Alert variant="destructive" className="p-3" data-testid="add-error">{formError}</Alert>}
            {skipped.length > 0 && (
              <Alert className="p-3" data-testid="sheet-problems">
                <p className="font-medium">{plural(skipped.length, "row of the sheet was", "rows of the sheet were")} not used:</p>
                <ul className="mt-1 list-disc pl-5">{skipped.map((p) => <li key={p}>{p}</li>)}</ul>
              </Alert>
            )}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={!names.trim()} loading={busy}>{busy ? "Creating..." : "Create logins"}</Button>
              <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}><Upload /> Upload a sheet</Button>
              <Button type="button" variant="ghost" onClick={() => saveFile(SAMPLE_SHEET, "participants-sample-sheet.csv")}><Download /> Download sample sheet</Button>
              <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm" aria-label="Student sheet" className="hidden" onChange={readSheet} />
            </div>
            <p className="text-xs text-muted-foreground">The sheet can be CSV or Excel (.xlsx). Rows with an @example.com address are the sample rows and are skipped. Up to 200 people at a time. You can correct the list here before pressing Create logins, and correct any person later with Edit details.</p>
          </form>
        </CardContent>
      </Card>}

      {created && (
        <Card className="print-area" data-testid="credentials">
          <CardHeader>
            <CardTitle>Logins for {test.title}</CardTitle>
            <CardDescription>Sign in at {window.location.origin}, in Google Chrome or Microsoft Edge only (not Firefox or Brave). Passwords are shown only on this page, so this list keeps every login you create or send here. Print or download it before you leave. Lost one? Use Email login or New password for a person, or Get a fresh login sheet for everyone who has not started.</CardDescription>
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

      {recruit && (
        <Tabs value={view} onValueChange={setView}>
          <TabsList><TabsTrigger value="list" data-testid="list-tab">Participants</TabsTrigger><TabsTrigger value="bin" data-testid="bin-tab">Bin{paged.meta?.binned ? ` (${paged.meta.binned})` : ""}</TabsTrigger></TabsList>
        </Tabs>
      )}

      {view === "bin" ? <Card><CardHeader><CardTitle>Bin</CardTitle></CardHeader><CardContent><ParticipantBin testId={test.id} onChange={load} /></CardContent></Card> : <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Participants</CardTitle>
            {recruit && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => sendLogins(false)} disabled={!published || !logins?.waiting} loading={sending}><Mail /> Send logins by email{published && logins ? ` (${logins.waiting} waiting)` : ""}</Button>
                {published && <Button variant="ghost" size="sm" onClick={() => sendLogins(true)} disabled={sending}>Send to everyone again</Button>}
                <Button variant="outline" size="sm" onClick={freshSheet}>Get a fresh login sheet</Button>
              </div>
            )}
          </div>
          {recruit && !published && <p className="text-xs text-muted-foreground" data-testid="publish-first">Publish the exam first: logins can be e-mailed only for a published exam.</p>}
          {logins && (logins.sent + logins.queued + logins.failed + logins.changed + logins.waiting > 0) && (
            <p className="text-xs text-muted-foreground" data-testid="mail-summary">
              Login mails: {logins.sent} sent, {logins.queued} sending, {logins.failed} not delivered, {logins.changed} email changed, {logins.waiting} waiting, {logins.no_email} without an email.
              A mail counts as Sent when the mail server has accepted it.
            </p>
          )}
          {note && (
            <Alert className="p-3" data-testid="send-note">
              <p className="font-medium">{note.queued ? `${plural(note.queued, "login mail is", "login mails are")} on its way.` : "No mail was sent."}</p>
              <ul className="mt-1 list-disc pl-5 text-sm">
                {note.no_email > 0 && <li>{plural(note.no_email, "person has", "people have")} no email: give them the printed sheet.</li>}
                {note.busy > 0 && <li>{plural(note.busy, "person is", "people are")} taking another exam right now: send again after it ends.</li>}
                {note.remaining > 0 && <li>{note.remaining} more are waiting: press Send logins by email again.</li>}
                {note.queued > 0 && <li>The new passwords are also on the sheet above.</li>}
              </ul>
            </Alert>
          )}
          <Input className="mt-2 w-64" placeholder="Search by name or username" aria-label="Search participants" value={search} onChange={(e) => setSearch(e.target.value)} />
        </CardHeader>
        <CardContent>
          {rows === null && !paged.error && <Loading />}
          {paged.error && !rows && <p className="text-sm text-destructive">{paged.error}</p>}
          {rows && (
            <Table>
              <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Username</TableHead><TableHead>Email</TableHead><TableHead>Login mail</TableHead><TableHead>Status</TableHead><TableHead>Score</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.assignment_id} data-testid="participant-row">
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell className="font-mono text-xs">{r.username || r.email}</TableCell>
                    <TableCell className="text-xs" data-testid="participant-email">{hasEmail(r.email) ? r.email : <span className="text-muted-foreground">No email</span>}</TableCell>
                    <TableCell data-testid="login-mail"><MailCell mail={r.login_mail} /></TableCell>
                    <TableCell><Badge variant={r.status === "banned" ? "destructive" : "secondary"}>{STATUS[r.status] ?? r.status}</Badge></TableCell>
                    <TableCell>{r.score != null ? `${r.score} / ${r.max}` : "-"}</TableCell>
                    <TableCell className="text-right">
                      <AssignmentActions row={{ id: r.assignment_id, name: r.name, username: r.username || r.email, status: r.status, assignmentStatus: r.status,
                        participant: !!r.username, email: hasEmail(r.email) ? r.email : "", published, mail: r.login_mail }}
                        onDone={load} onSheet={(p) => setCreated((old) => merge(old, [p]))} />
                    </TableCell>
                  </TableRow>
                ))}
                {!rows.length && <TableRow><TableCell colSpan={7} className="text-muted-foreground">{search.trim() ? "Nobody matches." : "Nobody yet."}</TableCell></TableRow>}
              </TableBody>
            </Table>
          )}
          <MoreRows paged={paged} what="people" />
        </CardContent>
      </Card>}
    </div>
  )
}
