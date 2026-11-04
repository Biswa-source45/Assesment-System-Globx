import { useEffect, useRef, useState } from "react"
import { cn } from "cn"
import { api } from "@/lib/api"

// Camera pictures are protected files, so they are fetched with the login header and shown from memory.
export default function Snapshot({ id, alt = "Latest camera snapshot", className = "h-16 w-20" }) {
  const [url, setUrl] = useState(null)
  const shown = useRef(null)
  useEffect(() => {
    if (!id) return
    let alive = true
    api(`/snapshots/${id}`, { raw: true })
      .then((r) => r.blob())
      .then((b) => {
        if (!alive) return
        const next = URL.createObjectURL(b)
        if (shown.current) URL.revokeObjectURL(shown.current)
        shown.current = next
        setUrl(next)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [id])
  useEffect(() => () => { if (shown.current) URL.revokeObjectURL(shown.current) }, [])
  if (!id) return <span className="text-xs text-muted-foreground">-</span>
  return url ? <img src={url} alt={alt} className={cn("rounded object-cover", className)} /> : <span className={cn("inline-block rounded bg-muted", className)} />
}
