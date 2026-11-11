import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ChevronRight, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { GROUPS, TOPICS } from "./topics"

// Help for staff: topics that open and close, a search box, and playgrounds. The text of every topic is on the page all the time, so the
// search simply reads what is shown (there is no second copy of the text to keep in step). A playground is built only while its topic is open.
export default function Help() {
  const [params] = useSearchParams()
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState(() => new Set())
  const [hidden, setHidden] = useState(() => new Set())
  const refs = useRef({})

  // /admin/help?topic=json-route opens that topic and scrolls to it
  const wanted = params.get("topic")
  useEffect(() => {
    if (!TOPICS.some((t) => t.id === wanted)) return
    setOpen((o) => new Set(o).add(wanted))
    requestAnimationFrame(() => refs.current[wanted]?.scrollIntoView({ block: "start" }))
  }, [wanted])

  // every typed word must appear in the topic; matching topics open, the others are hidden
  useEffect(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    if (!words.length) return setHidden(new Set())
    const hit = TOPICS.filter((t) => { const text = refs.current[t.id]?.textContent.toLowerCase() ?? ""; return words.every((w) => text.includes(w)) }).map((t) => t.id)
    setHidden(new Set(TOPICS.map((t) => t.id).filter((id) => !hit.includes(id))))
    setOpen(new Set(hit))
  }, [query])

  const shown = TOPICS.length - hidden.size
  const toggle = (id, isOpen) => setOpen((o) => (o.has(id) === isOpen ? o : (() => { const n = new Set(o); isOpen ? n.add(id) : n.delete(id); return n })()))

  return (
    <div className="mx-auto grid max-w-4xl gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Help</h1>
        <p className="text-sm text-muted-foreground">How to create questions and exams, the file formats, and a place to try things. Click a title to open it.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 grow">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label="Search help" placeholder="Search help, for example: negative marks, hidden test case, passwords" className="pl-8" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {query && <Button variant="outline" onClick={() => setQuery("")}><X /> Clear</Button>}
        <Button variant="outline" onClick={() => setOpen(new Set(TOPICS.filter((t) => !hidden.has(t.id)).map((t) => t.id)))}>Open all</Button>
        <Button variant="outline" onClick={() => setOpen(new Set())}>Close all</Button>
      </div>
      <p role="status" className="text-sm text-muted-foreground" data-testid="help-count">
        {query ? (shown ? `${shown} ${shown === 1 ? "topic matches" : "topics match"} "${query.trim()}".` : `No topic matches "${query.trim()}". Try fewer or different words.`) : `${TOPICS.length} topics`}
      </p>

      {GROUPS.map(([group, label]) => {
        const topics = TOPICS.filter((t) => t.group === group)
        if (topics.every((t) => hidden.has(t.id))) return null
        return (
          <section key={group} className="grid gap-2">
            <h2 className="mt-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{label}</h2>
            {topics.map((t) => (
              <details key={t.id} id={`topic-${t.id}`} ref={(el) => { refs.current[t.id] = el }} open={open.has(t.id)} data-testid="topic"
                onToggle={(e) => toggle(t.id, e.currentTarget.open)} className={"group rounded-lg border bg-card " + (hidden.has(t.id) ? "hidden" : "")}>
                <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 font-medium [&::-webkit-details-marker]:hidden">
                  <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" />{t.title}
                </summary>
                <div className="grid gap-3 border-t px-4 py-4 text-sm leading-relaxed">
                  {t.body}
                  {t.play && open.has(t.id) && t.play}
                </div>
              </details>
            ))}
          </section>
        )
      })}
    </div>
  )
}
