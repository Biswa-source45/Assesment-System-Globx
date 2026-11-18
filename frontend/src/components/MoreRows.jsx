import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/Spinner"

// Under a long list: loads the next page when it scrolls into view, says how many are shown, and has a button for anyone who prefers to press.
// `paged` is what usePaged returned; `what` names the rows ("questions").
export default function MoreRows({ paged, what = "rows" }) {
  const { rows, total, busy, error, more, done } = paged
  const end = useRef(null)
  const ask = useRef(more)
  ask.current = more
  useEffect(() => {
    if (!end.current || done || busy || error || !rows?.length) return
    const watch = new IntersectionObserver(([e]) => { if (e.isIntersecting) ask.current() }, { rootMargin: "300px" })
    watch.observe(end.current)
    return () => watch.disconnect()
  }, [done, busy, error, rows?.length])
  if (!rows?.length) return null
  return (
    <div ref={end} className="flex min-h-10 flex-wrap items-center justify-center gap-3 py-2 text-sm text-muted-foreground" data-testid="more-rows">
      <span data-testid="shown-count">Showing {rows.length.toLocaleString()} of {total.toLocaleString()} {what}</span>
      {busy && <span className="flex items-center gap-1.5" role="status"><Spinner />Loading...</span>}
      {error && <><span className="text-destructive" role="alert">{error}</span><Button size="sm" variant="outline" onClick={more}>Try again</Button></>}
      {!busy && !error && !done && <Button size="sm" variant="outline" onClick={more}>Load more</Button>}
    </div>
  )
}
