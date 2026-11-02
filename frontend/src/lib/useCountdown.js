import { useEffect, useState } from "react"

// Seconds left until `deadlineIso`, using the server clock (skewMs = server time - browser time at load).
export function useCountdown(deadlineIso, skewMs = 0) {
  const calc = () => (deadlineIso ? Math.max(0, Math.round((new Date(deadlineIso).getTime() - (Date.now() + skewMs)) / 1000)) : null)
  const [left, setLeft] = useState(calc)
  useEffect(() => {
    setLeft(calc())
    const id = setInterval(() => setLeft(calc()), 1000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deadlineIso, skewMs])
  return left
}

export function hms(s) {
  if (s == null) return "--:--"
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  return (h ? `${h}:` : "") + `${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`
}
