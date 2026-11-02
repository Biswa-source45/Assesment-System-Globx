import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const LABEL = { invited: "Ready", in_progress: "In progress", banned: "Locked", test_taken: "Submitted", review_pending: "Submitted", evaluated: "Marked" }

export default function CandidateHome() {
  const { user, logout } = useAuth()
  const [items, setItems] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/me/assignments").then(setItems).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="flex items-center justify-between border-b bg-white px-6 py-3">
        <span className="font-brand text-lg font-bold">GLOBX <span className="text-primary">Assess</span></span>
        <div className="flex items-center gap-3 text-sm">
          <span>{user.name || user.email}</span>
          <Button variant="outline" size="sm" onClick={logout}>Sign out</Button>
        </div>
      </header>
      <main className="mx-auto grid max-w-2xl gap-4 p-6">
        <h1 className="text-2xl font-semibold">Your exams</h1>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {items?.map((a) => (
          <Card key={a.assignment_id}>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle>{a.test.title}</CardTitle>
                <Badge variant={a.status === "banned" ? "destructive" : "secondary"}>{LABEL[a.status] ?? a.status}</Badge>
              </div>
              <CardDescription>{a.test.duration_min} minutes</CardDescription>
            </CardHeader>
            <CardContent className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>{a.message || (a.can_start ? "You can start this exam now." : "")}</span>
              {a.can_start && <Button asChild><Link to={`/exam/${a.assignment_id}/start`}>{a.attempt ? "Resume" : "Start"}</Link></Button>}
            </CardContent>
          </Card>
        ))}
        {items && !items.length && <p className="text-muted-foreground">No exams assigned.</p>}
      </main>
    </div>
  )
}
