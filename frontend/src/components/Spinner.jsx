import { useEffect, useState, useSyncExternalStore } from "react"
import { Loader2 } from "lucide-react"
import { cn } from "cn"
import { requestsWaiting, watchRequests } from "@/lib/api"

// The one round spinner of the app.
export function Spinner({ className }) {
  return <Loader2 className={cn("size-4 animate-spin text-primary", className)} aria-hidden="true" />
}

// What a page or a table shows while its first data is on the way.
export function Loading({ label = "Loading...", className }) {
  return <div role="status" className={cn("flex items-center justify-center gap-2 p-6 text-sm text-muted-foreground", className)}><Spinner className="size-5" />{label}</div>
}

// A small round spinner in the top corner while any click or page is waiting for the server for more than 0.3 s (a quick answer never flashes it).
// Requests that only keep something up to date are sent with { quiet: true } and do not count (see lib/api.js).
export function BusyChip() {
  const waiting = useSyncExternalStore(watchRequests, requestsWaiting) > 0
  const [show, setShow] = useState(false)
  useEffect(() => {
    if (!waiting) { setShow(false); return }
    const t = setTimeout(() => setShow(true), 300)
    return () => clearTimeout(t)
  }, [waiting])
  if (!show) return null
  return (
    <div role="status" aria-label="Loading" data-testid="busy-chip" className="pointer-events-none fixed top-3 right-4 z-[80] grid size-10 place-items-center rounded-full border bg-white shadow-md">
      <Spinner className="size-5" />
    </div>
  )
}
