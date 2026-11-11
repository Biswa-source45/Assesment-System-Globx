import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { ENDED } from "@/lib/labels"
import { RESULT, TONE } from "@/lib/verdict"
import { Badge } from "@/components/ui/badge"
import Brand from "@/components/Brand"
import SignOutButton from "@/components/SignOutButton"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

// "Marked" is not shown: a candidate hears about a result only when it has been declared
const LABEL = { invited: "Ready", in_progress: "In progress", banned: "Locked", test_taken: "Submitted", review_pending: "Submitted", evaluated: "Submitted" }

export default function CandidateHome() {
  const { user } = useAuth()
  const [items, setItems] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/me/assignments").then(setItems).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="min-h-svh bg-muted/40">
      <header className="flex items-center justify-between border-b bg-white px-6 py-3">
        <Brand />
        <div className="flex items-center gap-3 text-sm">
          <span>{user.name || user.email}</span>
          <SignOutButton />
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
                <Badge variant={a.status === "banned" ? "destructive" : "secondary"}>{a.result ? "Result declared" : (LABEL[a.status] ?? a.status)}</Badge>
              </div>
              <CardDescription>{a.test.duration_min} minutes</CardDescription>
            </CardHeader>
            <CardContent className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>{a.result ? "" : a.message || (a.can_start ? "You can start this exam now." : "")}</span>
              {a.can_start && <Button asChild><Link to={`/exam/${a.assignment_id}/start`}>{a.attempt ? "Resume" : "Start"}</Link></Button>}
            </CardContent>
            {a.result && (
              <CardContent className="grid gap-2 border-t pt-4 text-sm" data-testid="my-result">
                <div className="flex items-center gap-3">
                  <span className="text-xl font-semibold" data-testid="my-score">{a.result.score} / {a.result.max} ({a.result.percent}%)</span>
                  {a.result.result !== "no_pass_mark" && <Badge variant="outline" className={TONE[RESULT[a.result.result][1]]}>{RESULT[a.result.result][0]}</Badge>}
                </div>
                {a.result.result === "not_attempted" && <p className="text-muted-foreground">You did not answer any question.</p>}
                {ENDED[a.result.reason] && a.result.reason !== "submitted" && <p className="text-muted-foreground">{ENDED[a.result.reason]}</p>}
                <div className="flex flex-wrap gap-x-4 text-muted-foreground">{a.result.sections.map((s) => <span key={s.title}>{s.title}: {s.score} / {s.max}</span>)}</div>
              </CardContent>
            )}
          </Card>
        ))}
        {items && !items.length && <p className="text-muted-foreground">No exams assigned.</p>}
      </main>
    </div>
  )
}
