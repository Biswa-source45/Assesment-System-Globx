import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import { Eye, EyeOff, KeyRound, Pencil, Plus, Shuffle } from "lucide-react"
import { get, post, put } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate } from "@/lib/labels"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

// What each role may do. The server enforces this (backend/app/core/deps.py ROLE_GROUPS); these lines only explain it.
const ROLES = [
  ["super_admin", "Super Admin", "Everything, including other Super Admins and organisations."],
  ["org_admin", "Org Admin", "Everything in the organisation: users, exams, questions, monitoring, marking, audit log."],
  ["test_creator", "Test Creator", "Builds exams, questions and departments, adds participants, watches the live monitor."],
  ["recruiter", "Recruiter", "Adds participants and their logins; extends, ends and re-opens exams; watches the live monitor. Cannot see the question bank."],
  ["evaluator", "Evaluator", "Reads the question bank and marks answers; watches the live monitor."],
]
const ROLE_LABEL = { ...Object.fromEntries(ROLES.map(([k, name]) => [k, name])), candidate: "Candidate" }

// 12 characters from a clear alphabet (no 0/O, 1/l/I), always with letters and digits, from the browser's secure random source.
function generatePassword() {
  const pick = (chars, n) => Array.from(crypto.getRandomValues(new Uint32Array(n)), (x) => chars[x % chars.length]).join("")
  return pick("abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789", 10) + pick("abcdefghjkmnpqrstuvwxyz", 1) + pick("23456789", 1)
}

function PasswordField({ id, value, onChange }) {
  const [shown, setShown] = useState(false)
  return (
    <div className="flex gap-2">
      <Input id={id} type={shown ? "text" : "password"} autoComplete="new-password" value={value} onChange={(e) => onChange(e.target.value)} className="font-mono" />
      <Button type="button" variant="outline" size="icon" aria-label={shown ? "Hide password" : "Show password"} onClick={() => setShown(!shown)}>{shown ? <EyeOff /> : <Eye />}</Button>
      <Button type="button" variant="outline" onClick={() => { onChange(generatePassword()); setShown(true) }}><Shuffle /> Generate</Button>
    </div>
  )
}

// "new" creates a staff user; an existing row edits name, email, roles and status (a candidate: name and status only).
function UserDialog({ target, me, onClose, onSaved }) {
  const isNew = target === "new"
  const candidate = !isNew && target.roles.includes("candidate")
  const self = !isNew && target.id === me.id
  const [f, setF] = useState(() => (isNew ? { name: "", email: "", roles: [], status: "active", password: "" }
    : { name: target.name, email: target.email, roles: target.roles, status: target.status, password: "" }))
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const toggle = (r) => set("roles", f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r])

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const body = isNew ? f : { name: f.name, email: candidate ? "" : f.email, roles: candidate ? [] : f.roles, status: f.status }
      await (isNew ? post("/users", body) : put(`/users/${target.id}`, body))
      toast.success(isNew ? "User created" : "User saved")
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
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={save} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{isNew ? "Add a user" : `Edit ${target.name || target.email}`}</DialogTitle>
            <DialogDescription>{candidate ? "This person signs in with a login made for an exam. Roles do not apply." : "Staff sign in with their email and password."}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5"><Label htmlFor="u-name">Name</Label><Input id="u-name" required value={f.name} onChange={(e) => set("name", e.target.value)} /></div>
          {!candidate && <div className="grid gap-1.5"><Label htmlFor="u-email">Email</Label><Input id="u-email" type="email" required value={f.email} onChange={(e) => set("email", e.target.value)} /></div>}
          {!candidate && (
            <div className="grid gap-2">
              <Label>Roles</Label>
              {ROLES.filter(([k]) => k !== "super_admin" || me.can.super || f.roles.includes(k)).map(([k, name, help]) => (
                <Label key={k} className="flex items-start gap-3 rounded-md border p-2 font-normal has-[[data-disabled]]:opacity-60">
                  <Checkbox className="mt-0.5" checked={f.roles.includes(k)} disabled={self} onCheckedChange={() => toggle(k)} aria-label={name} />
                  <span className="grid gap-0.5"><span className="font-medium">{name}</span><span className="text-xs text-muted-foreground">{help}</span></span>
                </Label>
              ))}
              {self && <p className="text-xs text-muted-foreground">You cannot change your own roles. Ask another administrator.</p>}
            </div>
          )}
          {isNew && (
            <div className="grid gap-1.5">
              <Label htmlFor="u-pass">First password</Label>
              <PasswordField id="u-pass" value={f.password} onChange={(v) => set("password", v)} />
              <p className="text-xs text-muted-foreground">At least 8 characters with letters and digits. Tell the person; they can change it after signing in.</p>
            </div>
          )}
          {!isNew && (
            <div className="grid gap-1.5">
              <Label>Status</Label>
              <Select value={f.status} onValueChange={(v) => set("status", v)} disabled={self}>
                <SelectTrigger className="w-48" aria-label="Status"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="active">Active</SelectItem><SelectItem value="disabled">Disabled (cannot sign in)</SelectItem></SelectContent>
              </Select>
              {self && <p className="text-xs text-muted-foreground">You cannot disable yourself.</p>}
            </div>
          )}
          {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || (!candidate && !f.roles.length)}>{busy ? "Saving..." : isNew ? "Create user" : "Save user"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function PasswordDialog({ target, onClose, onSaved }) {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      await put(`/users/${target.id}`, { password })
      toast.success(`New password set for ${target.name || target.email}. Their open sessions were signed out.`)
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
            <DialogTitle>Change password for {target.name || target.email}</DialogTitle>
            <DialogDescription>They are signed out everywhere and must use the new password. Tell them the new password yourself; it is not shown again.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5"><Label htmlFor="new-pass">New password</Label><PasswordField id="new-pass" value={password} onChange={setPassword} /></div>
          {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || !password}>{busy ? "Saving..." : "Set password"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const statusBadge = (u) => (u.locked ? <Badge variant="destructive">Locked</Badge> : u.status === "disabled" ? <Badge variant="outline">Disabled</Badge> : <Badge variant="secondary">Active</Badge>)

export default function Users() {
  const { user: me } = useAuth()
  const [tab, setTab] = useState("staff")
  const [staff, setStaff] = useState(null)
  const [candidates, setCandidates] = useState(null)
  const [search, setSearch] = useState("")
  const [role, setRole] = useState("all")
  const [dialog, setDialog] = useState(null)  // { kind: "edit" | "password", target } or { kind: "edit", target: "new" }

  const load = useCallback(() => {
    get("/users").then(setStaff).catch((e) => toast.error(e.message))
    get("/users?role=candidate").then(setCandidates).catch((e) => toast.error(e.message))
  }, [])
  useEffect(load, [load])

  async function unlock(u) {
    try { await put(`/users/${u.id}`, { unlock: true }); toast.success(`${u.name || u.email} can sign in again`); load() } catch (e) { toast.error(e.message) }
  }

  const q = search.trim().toLowerCase()
  const match = (u) => [u.name, u.email, u.username, ...(u.exams ?? [])].some((v) => v?.toLowerCase().includes(q))
  const rows = ((tab === "staff" ? staff : candidates) ?? []).filter((u) => match(u) && (tab !== "staff" || role === "all" || u.roles.includes(role)))
  const protectedRow = (u) => u.roles.includes("super_admin") && !me.can.super  // only a Super Admin may change a Super Admin

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Users</h1>
          <p className="text-sm text-muted-foreground">Everyone who can sign in. Staff sign in with an email; candidates with the login made for their exam.</p>
        </div>
        <Button onClick={() => setDialog({ kind: "edit", target: "new" })}><Plus /> Add user</Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="staff">Staff ({staff?.length ?? "..."})</TabsTrigger>
            <TabsTrigger value="candidates">Candidates ({candidates?.length ?? "..."})</TabsTrigger>
          </TabsList>
        </Tabs>
        <Input className="w-64" placeholder="Search by name, email or exam" aria-label="Search users" value={search} onChange={(e) => setSearch(e.target.value)} />
        {tab === "staff" && (
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger className="w-44" aria-label="Filter by role"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All roles</SelectItem>
              {ROLES.map(([k, name]) => <SelectItem key={k} value={k}>{name}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead><TableHead>{tab === "staff" ? "Email" : "Username"}</TableHead><TableHead>{tab === "staff" ? "Roles" : "Exams"}</TableHead>
            <TableHead>Status</TableHead><TableHead>Last sign-in</TableHead><TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((u) => (
            <TableRow key={u.id} data-testid="user-row">
              <TableCell className="font-medium">{u.name || "-"} {u.id === me.id && <Badge variant="outline" className="ml-1">You</Badge>}</TableCell>
              <TableCell className={tab === "staff" ? "" : "font-mono text-xs"}>{tab === "staff" ? u.email : u.username}</TableCell>
              <TableCell>
                {tab === "staff"
                  ? <div className="flex flex-wrap gap-1">{u.roles.map((r) => <Badge key={r} variant="secondary">{ROLE_LABEL[r] ?? r}</Badge>)}</div>
                  : <span className="text-sm">{u.exams?.join(", ") || "-"}</span>}
              </TableCell>
              <TableCell>{statusBadge(u)}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{u.last_login_at ? fmtDate(u.last_login_at) : "Never"}</TableCell>
              <TableCell className="text-right">
                {u.locked && <Button variant="outline" size="sm" onClick={() => unlock(u)} aria-label={`Unlock ${u.name || u.email}`}>Unlock</Button>}
                <Button variant="edit" size="icon" aria-label={`Edit ${u.name || u.email}`} title="Edit" disabled={protectedRow(u)} onClick={() => setDialog({ kind: "edit", target: u })}><Pencil /></Button>
                <Button variant="edit" size="icon" className="ml-1" title="Change password" aria-label={`Change password for ${u.name || u.email}`} disabled={protectedRow(u)} onClick={() => setDialog({ kind: "password", target: u })}><KeyRound /></Button>
              </TableCell>
            </TableRow>
          ))}
          {!rows.length && <TableRow><TableCell colSpan={6} className="text-muted-foreground">{(tab === "staff" ? staff : candidates) ? "Nobody matches." : "Loading..."}</TableCell></TableRow>}
        </TableBody>
      </Table>

      {dialog?.kind === "edit" && <UserDialog key={dialog.target === "new" ? "new" : dialog.target.id} target={dialog.target} me={me} onClose={() => setDialog(null)} onSaved={load} />}
      {dialog?.kind === "password" && <PasswordDialog key={dialog.target.id} target={dialog.target} onClose={() => setDialog(null)} onSaved={load} />}
    </div>
  )
}
