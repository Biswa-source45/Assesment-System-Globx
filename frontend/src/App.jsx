import { Navigate, Route, Routes } from "react-router-dom"
import { useAuth } from "@/lib/auth"
import Login from "@/pages/Login"
import AdminLayout from "@/pages/admin/AdminLayout"
import Exams from "@/pages/admin/Exams"
import ComingSoon from "@/pages/admin/ComingSoon"
import CandidateHome from "@/pages/candidate/Home"

// Sends signed-out visitors to /login and keeps candidates out of the admin area (and staff out of the exam area).
function Guard({ staff, children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-8 text-muted-foreground">Loading...</div>
  if (!user) return <Navigate to="/login" replace />
  if (staff !== user.is_staff) return <Navigate to={user.is_staff ? "/admin" : "/exam"} replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/admin" element={<Guard staff><AdminLayout /></Guard>}>
        <Route index element={<Exams />} />
        <Route path="questions" element={<ComingSoon title="Question bank" />} />
        <Route path="results" element={<ComingSoon title="Results and review" />} />
        <Route path="monitor" element={<ComingSoon title="Live monitor" />} />
      </Route>
      <Route path="/exam" element={<Guard staff={false}><CandidateHome /></Guard>} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
