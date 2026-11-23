import { useEffect, useState } from "react"
import { toast } from "sonner"
import { post, put } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { fmtDate } from "@/lib/labels"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const ROLE_LABEL = { super_admin: "Super Admin", org_admin: "Org Admin", test_creator: "Test Creator", recruiter: "Recruiter", evaluator: "Evaluator" }

// Two steps: the new address, then the 6-digit code that was mailed to the CURRENT address. Nothing changes before the code is right.
function EmailDialog({ onClose, onDone }) {
  const [email, setEmail] = useState("")
  const [sent, setSent] = useState(null)  // the server's answer to step 1
  const [code, setCode] = useState("")
  const [wait, setWait] = useState(0)     // seconds until a new code may be asked for
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (wait <= 0) return
    const t = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  async function ask(e) {
    e?.preventDefault()
    setBusy(true)
    setError("")
    try {
      const r = await post("/auth/email-change/request", { new_email: email })
      setSent(r)
      setCode("")
      setWait(r.resend_after_s ?? 60)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function confirm(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      await post("/auth/email-change/confirm", { code })
      toast.success("Your e-mail was changed. Sign in with the new address next time.")
      onDone()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="email-dialog">
        {!sent ? (
          <form onSubmit={ask} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Change your e-mail</DialogTitle>
              <DialogDescription>Type the new address. A 6-digit code is sent to your <b>current</b> address to confirm that it is you.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-1.5"><Label htmlFor="new-email">New e-mail</Label><Input id="new-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" disabled={busy || !email.trim()} loading={busy}>{busy ? "Sending..." : "Send code"}</Button>
            </DialogFooter>
          </form>
        ) : (
          <form onSubmit={confirm} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Enter the code</DialogTitle>
              <DialogDescription>We sent a 6-digit code to <b>{sent.to}</b> (your current e-mail). It is valid for {sent.valid_minutes} minutes. Your e-mail becomes <b>{email.trim().toLowerCase()}</b> when the code is right.</DialogDescription>
            </DialogHeader>
            {sent.demo_otp && <Alert className="p-3" data-testid="demo-code">{sent.message} Code: <b>{sent.demo_otp}</b></Alert>}
            <div className="grid gap-1.5">
              <Label htmlFor="email-code">Code</Label>
              <Input id="email-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus className="w-40 font-mono text-lg tracking-widest" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            </div>
            {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
            <DialogFooter className="sm:justify-between">
              <Button type="button" variant="outline" disabled={busy || wait > 0} onClick={ask}>{wait > 0 ? `Send a new code (${wait} s)` : "Send a new code"}</Button>
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
                <Button type="submit" disabled={busy || code.length !== 6} loading={busy}>{busy ? "Checking..." : "Change e-mail"}</Button>
              </div>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Details() {
  const { user, refresh } = useAuth()
  const [name, setName] = useState(user.name || "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [emailOpen, setEmailOpen] = useState(false)

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      await put("/auth/profile", { name })
      await refresh()
      toast.success("Your name was saved")
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle>Your details</CardTitle><CardDescription>Your roles and organisation are set by an administrator.</CardDescription></CardHeader>
      <CardContent className="grid gap-4">
        <form onSubmit={save} className="grid gap-1.5">
          <Label htmlFor="p-name">Name</Label>
          <div className="flex gap-2">
            <Input id="p-name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
            <Button type="submit" disabled={busy || !name.trim() || name.trim() === (user.name || "")} loading={busy}>Save name</Button>
          </div>
        </form>
        {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
        <div className="grid gap-1.5">
          <Label>E-mail</Label>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium" data-testid="profile-email">{user.email}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => setEmailOpen(true)}>Change e-mail</Button>
          </div>
          <p className="text-xs text-muted-foreground">To change it, a code is sent to this address first.</p>
        </div>
        <div className="grid gap-1.5"><Label>Roles</Label><div className="flex flex-wrap gap-1">{user.roles.map((r) => <Badge key={r} variant="secondary">{ROLE_LABEL[r] ?? r}</Badge>)}</div></div>
        <div className="grid gap-1.5"><Label>Organisation</Label><span>{user.org_name || "-"}</span></div>
        <div className="grid gap-1.5"><Label>Last sign-in</Label><span>{user.last_login_at ? fmtDate(user.last_login_at) : "-"}</span></div>
      </CardContent>
      {emailOpen && <EmailDialog onClose={() => setEmailOpen(false)} onDone={refresh} />}
    </Card>
  )
}

function Password() {
  const [f, setF] = useState({ current: "", next: "", again: "" })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }))

  async function save(e) {
    e.preventDefault()
    setError("")
    if (f.next !== f.again) return setError("The two new passwords are not the same")
    setBusy(true)
    try {
      await post("/auth/password", { current_password: f.current, new_password: f.next })
      toast.success("Your password was changed")
      setF({ current: "", next: "", again: "" })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle>Password</CardTitle><CardDescription>At least 8 characters with letters and digits.</CardDescription></CardHeader>
      <CardContent>
        <form onSubmit={save} className="grid gap-3">
          <div className="grid gap-1.5"><Label htmlFor="p-cur">Current password</Label><Input id="p-cur" type="password" autoComplete="current-password" required value={f.current} onChange={set("current")} /></div>
          <div className="grid gap-1.5"><Label htmlFor="p-new">New password</Label><Input id="p-new" type="password" autoComplete="new-password" required value={f.next} onChange={set("next")} /></div>
          <div className="grid gap-1.5"><Label htmlFor="p-again">New password again</Label><Input id="p-again" type="password" autoComplete="new-password" required value={f.again} onChange={set("again")} /></div>
          {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
          <div><Button type="submit" disabled={busy || !f.current || !f.next} loading={busy}>{busy ? "Saving..." : "Change password"}</Button></div>
        </form>
      </CardContent>
    </Card>
  )
}

export default function Profile() {
  return (
    <div className="grid max-w-2xl gap-4" data-testid="profile">
      <div>
        <h1 className="text-2xl font-semibold">My profile</h1>
        <p className="text-sm text-muted-foreground">Your own details. Change your name, your password and your e-mail here.</p>
      </div>
      <Details />
      <Password />
    </div>
  )
}
