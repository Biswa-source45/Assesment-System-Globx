import { Link, useParams, useSearchParams } from "react-router-dom"
import { CheckCircle2, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const MESSAGES = {
  force_submit: ["Exam ended", "You left the exam window more times than allowed, so your exam was ended and your answers were submitted."],
  ban: ["Exam terminated", "Your face was not visible too many times. Your exam was ended and your login is locked. Please speak to the invigilator."],
  time: ["Time is up", "Your answers were submitted automatically."],
}

export default function Done() {
  const { attemptId } = useParams()
  const [params] = useSearchParams()
  const [title, text] = MESSAGES[params.get("why")] ?? ["Exam submitted", "Thank you. Your answers were received. Results will be shared by the organiser."]
  const bad = params.get("why") === "ban" || params.get("why") === "force_submit"
  const Icon = bad ? ShieldAlert : CheckCircle2
  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md text-center" data-attempt={attemptId}>
        <CardHeader className="items-center">
          <Icon className={"size-12 " + (bad ? "text-destructive" : "text-primary")} />
          <CardTitle className="text-xl" data-testid="done-title">{title}</CardTitle>
          <CardDescription>{text}</CardDescription>
        </CardHeader>
        <CardContent><Button asChild variant="outline"><Link to="/exam">Back to my exams</Link></Button></CardContent>
      </Card>
    </div>
  )
}
