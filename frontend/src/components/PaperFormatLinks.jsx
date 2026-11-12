import { toast } from "sonner"
import { api } from "@/lib/api"

// The question paper format, as a Word file with example pictures or as plain text. The server makes both when asked (they need the person's login, so
// the file is fetched and saved from here instead of being a plain link).
async function save(kind) {
  try {
    const blob = await (await api(`/help/paper-format.${kind}`, { raw: true })).blob()
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `KAUTILYA-question-paper-format.${kind}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(a.href), 2000)
  } catch (e) {
    toast.error(e.message)
  }
}

export default function PaperFormatLinks() {
  return (
    <span data-testid="paper-format-links">
      <button type="button" className="underline" onClick={() => save("docx")}>Word (.docx, with example pictures)</button>
      {" or "}
      <button type="button" className="underline" onClick={() => save("txt")}>text (.txt)</button>
    </span>
  )
}
