import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"

// A title that only repeats the start of the question text (a paper's questions have no names) is not shown a second time.
const plain = (s) => (s || "").replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/gi, " ").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
export const echoes = (title, html) => { const t = plain((title || "").replace(/\.\.\.$/, "")); return t.length > 0 && plain(html).includes(t) }

// Question bodies are sanitised on the server before they are stored.
export const Html = ({ html }) => <div className="q-html" dangerouslySetInnerHTML={{ __html: html || "" }} />

// An answer option: its words, and its picture when it has one (a figure to choose).
const Option = ({ o }) => (
  <span className="grid gap-1">
    {o.text && <span>{o.text}</span>}
    {o.image && <img src={o.image} alt={o.text ? `Picture for ${o.text}` : "Answer picture"} className="max-h-40 w-auto max-w-full rounded border bg-white object-contain" />}
  </span>
)

export function McqView({ q, r, onChange, closed }) {
  const selected = r.selected ?? []
  if (!q.multi) {
    return (
      <RadioGroup value={selected[0] ?? ""} onValueChange={(v) => onChange({ selected: [v] }, true)} disabled={closed} className="gap-2">
        {q.options.map((o) => (
          <Label key={o.id} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-secondary">
            <RadioGroupItem value={o.id} /> <Option o={o} />
          </Label>
        ))}
      </RadioGroup>
    )
  }
  const toggle = (id) => onChange({ selected: selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id] }, true)
  return (
    <div className="grid gap-2">
      {q.options.map((o) => (
        <Label key={o.id} className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-secondary">
          <Checkbox checked={selected.includes(o.id)} disabled={closed} onCheckedChange={() => toggle(o.id)} /> <Option o={o} />
        </Label>
      ))}
      <p className="text-xs text-muted-foreground">More than one answer can be correct. Each wrong option you tick takes away 0.25 marks. Ticking every option scores 0.</p>
    </div>
  )
}

export const wordCount = (t) => (t || "").trim().split(/\s+/).filter(Boolean).length

export function TextView({ q, r, onChange, closed }) {
  const words = wordCount(r.text)
  return (
    <div className="grid gap-1.5">
      <Textarea
        aria-label="Your answer"
        value={r.text ?? ""}
        disabled={closed}
        onChange={(e) => onChange({ text: e.target.value })}
        className={q.type === "long" ? "min-h-64" : "min-h-32"}
        placeholder="Type your answer here"
      />
      <div className={"text-xs " + (q.max_words && words > q.max_words ? "text-destructive" : "text-muted-foreground")}>
        {words} words{q.max_words ? ` (limit ${q.max_words})` : ""}
      </div>
    </div>
  )
}
