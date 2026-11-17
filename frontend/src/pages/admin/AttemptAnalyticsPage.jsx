import { Link, useParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import AttemptAnalytics from "@/components/AttemptAnalytics"
import { Button } from "@/components/ui/button"

// The same page the candidate sees, opened by a reviewer from the candidate's review page.
export default function AttemptAnalyticsPage() {
  const { testId, attemptId } = useParams()
  return (
    <div className="grid max-w-5xl gap-4">
      <div><Button variant="outline" asChild><Link to={`/admin/results/${testId}/${attemptId}`}><ArrowLeft /> Back to the candidate</Link></Button></div>
      <AttemptAnalytics attemptId={attemptId} />
    </div>
  )
}
