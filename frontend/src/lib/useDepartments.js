import { useCallback, useEffect, useState } from "react"
import { get } from "@/lib/api"

// The organisation's departments (null while loading), a lookup by id, and a way to reload after a change.
export function useDepartments() {
  const [departments, setDepartments] = useState(null)
  const reload = useCallback(() => get("/departments").then(setDepartments).catch(() => setDepartments([])), [])
  useEffect(() => { reload() }, [reload])
  const byId = Object.fromEntries((departments ?? []).map((d) => [d.id, d]))
  return { departments, byId, reload }
}
