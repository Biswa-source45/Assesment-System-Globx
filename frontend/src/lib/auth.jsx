import { createContext, useContext, useEffect, useState } from "react"
import { get, hasTokens, post, refreshToken, setTokens } from "@/lib/api"

const AuthContext = createContext(null)
// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(hasTokens())

  useEffect(() => {
    if (!hasTokens()) return
    get("/auth/me").then(setUser).catch(() => setTokens(null)).finally(() => setLoading(false))
  }, [])

  // identifier = staff email, or the candidate username printed on the exam sheet
  async function login(identifier, password, totp) {
    const out = await post("/auth/login", { email: identifier, password, totp: totp || undefined })
    setTokens(out)
    setUser(out.user)
    return out.user
  }

  async function logout() {
    const rt = refreshToken()
    if (rt) await post("/auth/logout", { refresh_token: rt }).catch(() => {})
    setTokens(null)
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
}
