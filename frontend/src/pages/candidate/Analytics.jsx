import { Link, useParams } from "react-router-dom"
import { ArrowLeft, FileText } from "lucide-react"
import { useAuth } from "@/lib/auth"
import AttemptAnalytics from "@/components/AttemptAnalytics"
import Brand from "@/components/Brand"
import SignOutButton from "@/components/SignOutButton"
import { Button } from "@/components/ui/button"

export default function Analytics() {
  const { attemptId } = useParams()
  const { user } = useAuth()
  return (
    <div className="min-h-svh bg-muted/40">
      <header className="flex items-center justify-between border-b bg-white px-6 py-3">
        <Brand />
        <div className="flex items-center gap-3 text-sm"><span>{user.name || user.email}</span><SignOutButton /></div>
      </header>
      <main className="mx-auto grid max-w-4xl gap-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" asChild><Link to="/exam"><ArrowLeft /> Your exams</Link></Button>
          <Button variant="outline" asChild><Link to={`/exam/report/${attemptId}`}><FileText /> Report card</Link></Button>
        </div>
        <AttemptAnalytics attemptId={attemptId} />
      </main>
    </div>
  )
}
