import { useRef } from "react"
import { toast } from "sonner"
import { ImagePlus, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { fileToDataUrl } from "@/lib/image"

// Choose a picture file; hands back its data URI (or shows why not).
function useChoose(onPicture) {
  const ref = useRef(null)
  const choose = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (!file) return
    try { onPicture(await fileToDataUrl(file)) } catch (err) { toast.error(err.message) }
  }
  return [ref, choose]
}

// Pictures under a question's text: thumbnails with Remove, and a button to add one (a screenshot can also be pasted into the text box).
export function QuestionPictures({ images, onChange, max = 4 }) {
  const [ref, choose] = useChoose((src) => onChange([...images, src]))
  return (
    <div className="grid gap-2" data-testid="question-pictures">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {images.map((src, i) => (
            <div key={i} className="relative rounded-md border bg-card p-1">
              <img src={src} alt={`Picture ${i + 1} of the question`} className="h-24 w-auto max-w-48 object-contain" />
              <Button type="button" variant="danger" size="icon" className="absolute -right-2 -top-2 size-6" aria-label={`Remove picture ${i + 1}`} onClick={() => onChange(images.filter((_, j) => j !== i))}><X /></Button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <input ref={ref} type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" aria-label="Choose a picture for the question" onChange={choose} />
        <Button type="button" variant="outline" size="sm" disabled={images.length >= max} onClick={() => ref.current.click()}><ImagePlus /> Add picture</Button>
        <span className="text-xs text-muted-foreground">Shown under the question text. You can also paste a screenshot into the text box. Up to {max}.</span>
      </div>
    </div>
  )
}

// One picture for an answer option (a figure to choose).
export function OptionPicture({ value, onChange, n }) {
  const [ref, choose] = useChoose(onChange)
  return (
    <>
      <input ref={ref} type="file" accept="image/png,image/jpeg,image/gif,image/webp" className="hidden" aria-label={`Choose a picture for option ${n}`} onChange={choose} />
      {value ? (
        <span className="relative shrink-0">
          <img src={value} alt={`Picture of option ${n}`} className="h-9 w-auto max-w-16 rounded border object-contain" />
          <Button type="button" variant="danger" size="icon" className="absolute -right-2 -top-2 size-5" aria-label={`Remove picture of option ${n}`} onClick={() => onChange("")}><X className="size-3" /></Button>
        </span>
      ) : (
        <Button type="button" variant="outline" size="icon" aria-label={`Add picture to option ${n}`} title="Add a picture to this option" onClick={() => ref.current.click()}><ImagePlus /></Button>
      )}
    </>
  )
}
