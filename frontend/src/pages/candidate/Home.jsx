import { useEffect, useState } from "react"
import { get } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

// Placeholder: lists the candidate's exams. Check-in (camera, face) and the exam runner come next.
export default function CandidateHome() {
  const { user, logout } = useAuth()
  const [items, setItems] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    get("/me/assignments").then(setItems).catch((e) => setError(e.message))
  }, [])

  return (
    <div className="mx-auto grid max-w-2xl gap-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Hello, {user.name || user.email}</h1>
        <Button variant="outline" size="sm" onClick={logout}>Sign out</Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {items?.map((a) => (
        <Card key={a.assignment_id}>
          <CardHeader>
            <CardTitle>{a.test.title}</CardTitle>
            <CardDescription>{a.test.duration_min} minutes - status: {a.status}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">{a.message || (a.can_start ? "You can start this exam." : "")}</CardContent>
        </Card>
      ))}
      {items && !items.length && <p className="text-muted-foreground">No exams assigned.</p>}
    </div>
  )
}
