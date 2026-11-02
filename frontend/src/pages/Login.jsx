import { useState } from "react"
import { Navigate, useNavigate } from "react-router-dom"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [identifier, setIdentifier] = useState("")
  const [password, setPassword] = useState("")
  const [totp, setTotp] = useState("")
  const [needTotp, setNeedTotp] = useState(false)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={user.is_staff ? "/admin" : "/exam"} replace />

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const u = await login(identifier.trim(), password, totp)
      navigate(u.is_staff ? "/admin" : "/exam", { replace: true })
    } catch (err) {
      if (err.detail?.mfa_required) setNeedTotp(true)
      else setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">GLOBX Assess</CardTitle>
          <CardDescription>Sign in with the username and password you were given.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="identifier">Username or email</Label>
              <Input id="identifier" autoFocus required value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            {needTotp && (
              <div className="grid gap-2">
                <Label htmlFor="totp">Authenticator code</Label>
                <Input id="totp" inputMode="numeric" autoComplete="one-time-code" required value={totp} onChange={(e) => setTotp(e.target.value)} />
              </div>
            )}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
