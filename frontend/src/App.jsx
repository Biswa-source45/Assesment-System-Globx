import { Navigate, Route, Routes } from "react-router-dom"
import { useAuth } from "@/lib/auth"
import Login from "@/pages/Login"
import AdminLayout from "@/pages/admin/AdminLayout"
import Exams from "@/pages/admin/Exams"
import Help from "@/pages/admin/help/Help"
import AttemptReview from "@/pages/admin/AttemptReview"
import Departments from "@/pages/admin/Departments"
import ExamResults from "@/pages/admin/ExamResults"
import ExamEditor from "@/pages/admin/ExamEditor"
import Monitor from "@/pages/admin/Monitor"
import Questions from "@/pages/admin/Questions"
import Results from "@/pages/admin/Results"
import Users from "@/pages/admin/Users"
import { QuestionPage } from "@/pages/admin/QuestionEditor"
import CandidateHome from "@/pages/candidate/Home"
import CheckIn from "@/pages/candidate/CheckIn"
import Exam from "@/pages/candidate/Exam"
import Done from "@/pages/candidate/Done"
import ErrorBoundary from "@/components/ErrorBoundary"

// The screens need the permission list the server sends with the user. A backend that was not restarted after an update does not send it.
function ServerTooOld() {
  return (
    <div className="mx-auto grid max-w-lg gap-2 p-8">
      <h1 className="text-xl font-semibold">The server needs a restart</h1>
      <p className="text-muted-foreground">This screen is newer than the backend that is running. Stop the backend, restart the backend (<code>python -m uvicorn app.main:app --port 8000 --reload</code> in the backend folder), then reload this page.</p>
    </div>
  )
}

// Sends signed-out visitors to /login and keeps candidates out of the admin area (and staff out of the exam area).
function Guard({ staff, children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-8 text-muted-foreground">Loading...</div>
  if (!user) return <Navigate to="/login" replace />
  if (staff !== user.is_staff) return <Navigate to={user.is_staff ? "/admin" : "/exam"} replace />
  if (user.is_staff && !user.can) return <ServerTooOld />
  return children
}

// Keeps a screen away from people the server would refuse anyway (a typed-in address, an old bookmark).
function Need({ can, children }) {
  const { user } = useAuth()
  return user.can[can] ? children : <Navigate to="/admin" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/admin" element={<Guard staff><AdminLayout /></Guard>}>
        <Route index element={<Exams />} />
        <Route path="exams/:id" element={<ExamEditor />} />
        <Route path="questions" element={<Need can="bank"><Questions /></Need>} />
        <Route path="questions/:id" element={<Need can="author"><QuestionPage /></Need>} />
        <Route path="results" element={<Results />} />
        <Route path="results/:testId" element={<ExamResults />} />
        <Route path="results/:testId/:attemptId" element={<AttemptReview />} />
        <Route path="departments" element={<Departments />} />
        <Route path="monitor" element={<Monitor />} />
        <Route path="help" element={<Help />} />
        <Route path="users" element={<Need can="admin"><Users /></Need>} />
      </Route>
      <Route path="/exam" element={<Guard staff={false}><CandidateHome /></Guard>} />
      <Route path="/exam/:assignmentId/start" element={<Guard staff={false}><CheckIn /></Guard>} />
      <Route path="/exam/attempt/:attemptId" element={<Guard staff={false}><ErrorBoundary><Exam /></ErrorBoundary></Guard>} />
      <Route path="/exam/done/:attemptId" element={<Guard staff={false}><Done /></Guard>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
