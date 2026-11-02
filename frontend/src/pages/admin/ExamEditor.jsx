import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { get, post } from "@/lib/api"
import ExamDetails from "@/pages/admin/ExamDetails"
import ExamParticipants from "@/pages/admin/ExamParticipants"
import ExamQuestions from "@/pages/admin/ExamQuestions"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default function ExamEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const isNew = id === "new"
  const [test, setTest] = useState(null)
  const [error, setError] = useState("")
  const [problems, setProblems] = useState([])
  const [busy, setBusy] = useState(false)
  const tab = params.get("tab") ?? "details"

  useEffect(() => {
    if (!isNew) get(`/tests/${id}`).then(setTest).catch((e) => setError(e.message))
  }, [id, isNew])

  // Any change to the exam makes the last "cannot publish" list out of date, so it goes away.
  const changed = (t) => { setTest(t); setProblems([]) }

  async function publish() {
    setBusy(true)
    setProblems([])
    try {
      setTest(await post(`/tests/${id}/publish`))
      toast.success("Exam published")
    } catch (e) {
      setProblems(e.detail?.errors ?? [e.message])  // the server lists everything that is missing
    } finally {
      setBusy(false)
    }
  }

  async function unpublish() {
    if (!confirm("Unpublish this exam? Candidates will not be able to start it until you publish it again.")) return
    try {
      setTest(await post(`/tests/${id}/unpublish`))
    } catch (e) {
      toast.error(e.message)
    }
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!isNew && !test) return <p className="text-muted-foreground">Loading...</p>

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="grid gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{isNew ? "New exam" : test.title}</h1>
            {test && <Badge variant={test.status === "published" ? "default" : "secondary"} data-testid="exam-status">{test.status}</Badge>}
          </div>
          {test && <p className="text-sm text-muted-foreground">{test.question_count} questions, {test.total_marks} marks, {test.duration_min} minutes</p>}
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" asChild><Link to="/admin">All exams</Link></Button>
          {test?.status === "published" && <Button variant="outline" asChild><Link to={`/admin/monitor?exam=${test.id}`}>Live monitor</Link></Button>}
          {test?.status === "draft" && <Button onClick={publish} disabled={busy}>{busy ? "Publishing..." : "Publish"}</Button>}
          {test?.status === "published" && <Button variant="outline" onClick={unpublish}>Unpublish</Button>}
        </div>
      </div>

      {problems.length > 0 && (
        <Alert variant="destructive" className="p-3" data-testid="publish-problems">
          <p className="font-medium">The exam cannot be published yet:</p>
          <ul className="mt-1 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Alert>
      )}

      {isNew ? (
        <ExamDetails test={null} onSaved={(t) => navigate(`/admin/exams/${t.id}?tab=questions`)} />
      ) : (
        <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
          <TabsList>
            <TabsTrigger value="details">Details</TabsTrigger>
            <TabsTrigger value="questions">Questions</TabsTrigger>
            <TabsTrigger value="participants">Participants</TabsTrigger>
          </TabsList>
          <TabsContent value="details" className="pt-4"><ExamDetails test={test} onSaved={changed} /></TabsContent>
          <TabsContent value="questions" className="pt-4"><ExamQuestions test={test} setTest={changed} /></TabsContent>
          <TabsContent value="participants" className="pt-4"><ExamParticipants test={test} /></TabsContent>
        </Tabs>
      )}
    </div>
  )
}
