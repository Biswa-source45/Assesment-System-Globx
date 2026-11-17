import { useEffect, useState } from "react"
import { Download, Eye, FileText } from "lucide-react"
import { fetchFile, saveBlob } from "@/lib/download"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

// A button for a PDF that opens a small dialog first: Preview it here on screen, or Download it. (A plain link cannot do either: the file needs the sign-in token.)
export default function PdfButton({ path, name = "report-card.pdf", label = "PDF", title = "Report card", description = "", icon: Icon = FileText, ...buttonProps }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState(null)   // { blob, name, url } once loaded
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => () => file && URL.revokeObjectURL(file.url), [file])

  function close(o) {
    if (o) return setOpen(true)
    setOpen(false); setFile(null); setError("")
  }
  async function load() {
    if (file) return file
    const f = await fetchFile(path, name)
    const typed = new Blob([f.blob], { type: "application/pdf" })
    const loaded = { blob: typed, name: f.name, url: URL.createObjectURL(typed) }
    setFile(loaded)
    return loaded
  }
  async function run(then) {
    if (busy) return
    setBusy(true); setError("")
    try { await then(await load()) } catch (e) { setError(e.message || "This could not be opened.") } finally { setBusy(false) }
  }

  return (
    <>
      <Button {...buttonProps} onClick={() => setOpen(true)}><Icon /> {label}</Button>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent className={file?.preview ? "sm:max-w-4xl" : "sm:max-w-md"} data-testid="pdf-dialog">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description || "Look at it here first, or save it as a file."}</DialogDescription>
          </DialogHeader>
          {file?.preview ? (
            <div className="grid gap-2">
              <iframe title={`${title} preview`} src={file.url} className="h-[70vh] w-full rounded-md border bg-white" data-testid="pdf-preview" />
              <p className="text-xs text-muted-foreground">If the report does not appear here (some phones cannot show a PDF inside a page), use Download.</p>
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              <Button disabled={busy} onClick={() => run((f) => setFile({ ...f, preview: true }))}><Eye /> Preview</Button>
              <Button variant="outline" disabled={busy} onClick={() => run((f) => { saveBlob(f.blob, f.name); close(false) })}><Download /> Download</Button>
            </div>
          )}
          {busy && <p className="text-sm text-muted-foreground">Getting the file...</p>}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <DialogFooter>
            {file?.preview && <Button onClick={() => saveBlob(file.blob, file.name)}><Download /> Download</Button>}
            <DialogClose asChild><Button variant="outline">{file?.preview ? "Close" : "Cancel"}</Button></DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
