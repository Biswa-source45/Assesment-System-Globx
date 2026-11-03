import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { Maximize2, MessageSquare, Mic, MicOff } from "lucide-react"
import { LiveViewer } from "@/lib/live"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"

function Stream({ stream, className, label }) {
  const el = useRef(null)
  useEffect(() => {
    if (!el.current) return
    el.current.srcObject = stream
    if (stream) el.current.play().catch(() => {})
  }, [stream])
  return <video ref={el} muted playsInline autoPlay aria-label={label} data-live={stream ? "yes" : "no"} className={"rounded-md bg-black object-contain " + className} />
}

// What a tile says while no picture flows: never a silent black box.
const NOTE = { connecting: "Connecting...", connected: "" }
const noteOf = (state) => NOTE[state] ?? "Cannot connect: the network does not let these two computers send video to each other. Tell IT."
const badgeOf = (peer) => (!peer ? ["Not connected", "secondary"] : peer.state === "connected" ? ["Live", "default"] : peer.state === "connecting" ? ["Connecting", "secondary"] : ["Cannot connect", "destructive"])

// Every candidate in progress, live: their screen and camera, a message, a private line. Needs the exam's "Live view" setting on.
export default function LiveGrid({ testId, rows }) {
  const viewer = useRef(null)
  const [state, setState] = useState({ peers: [], talking: {} })
  const [focus, setFocus] = useState(null)   // candidate id shown large
  const [writing, setWriting] = useState(null)  // candidate id being written to
  const [text, setText] = useState("")

  useEffect(() => {
    const v = new LiveViewer({ testId, onChange: setState })
    v.onBusy = () => toast.error("Another invigilator is already talking to this candidate.")
    viewer.current = v
    return () => v.stop()
  }, [testId])

  const peerOf = (id) => state.peers.find((p) => p.id === id)
  const people = rows.filter((r) => r.status === "in_progress" && r.attempt)
  const me = () => viewer.current?.me

  async function talk(id) {
    try { await viewer.current.talk(id) } catch { toast.error("The microphone is blocked. Allow it in the address bar and try again.") }
  }

  function send(e) {
    e.preventDefault()
    viewer.current.message(writing, text.trim())
    toast.success("Message sent")
    setWriting(null)
    setText("")
  }

  const focused = focus && people.find((r) => r.attempt.id === focus)
  const tile = (r, big) => {
    const peer = peerOf(r.attempt.id)
    const note = peer && noteOf(peer.state)
    return (
      <div className="relative">
        <div className={"grid gap-2 " + (peer?.screen ? "grid-cols-[3fr_1fr]" : "grid-cols-1")}>
          {peer?.screen && <Stream stream={peer.screen} label={`${r.name} screen`} className="aspect-video w-full" />}
          <Stream stream={peer?.camera ?? null} label={`${r.name} camera`} className={"w-full " + (peer?.screen ? "aspect-[4/3] self-end" : "aspect-video")} />
        </div>
        {note && <p data-testid="live-note" className={"absolute inset-0 grid place-items-center p-4 text-center text-sm font-medium " + (peer.state === "connecting" ? "text-white/80" : "text-red-300")}>{note}</p>}
      </div>
    )
  }

  return (
    <div className="grid gap-3" data-testid="live-grid">
      {!people.length && <p className="text-sm text-muted-foreground">Nobody is taking the exam right now.</p>}
      <div className="grid gap-3 lg:grid-cols-2">
        {people.map((r) => {
          const peer = peerOf(r.attempt.id)
          const line = state.talking[r.attempt.id]
          const mine = line && line === me()
          return (
            <Card key={r.assignment_id} data-testid="live-card" data-name={r.name}>
              <CardContent className="grid gap-2 pt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="grow font-medium">{r.name}</span>
                  <Badge variant={badgeOf(peer)[1]} data-testid="live-state">{badgeOf(peer)[0]}</Badge>
                  <Badge variant={r.attempt.violations ? "destructive" : "secondary"}>Leaves {r.attempt.violations}</Badge>
                  <Badge variant={r.attempt.face_incidents ? "destructive" : "secondary"}>Face {r.attempt.face_incidents}</Badge>
                </div>
                {tile(r, false)}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant={mine ? "destructive" : "outline"} disabled={!peer || (!!line && !mine)} onClick={() => (mine ? viewer.current.stopTalk(r.attempt.id) : talk(r.attempt.id))}>
                    {mine ? <><MicOff /> End talk</> : <><Mic /> {line ? "Line in use" : "Talk"}</>}
                  </Button>
                  <Button size="sm" variant="outline" disabled={!peer} onClick={() => setWriting(r.attempt.id)}><MessageSquare /> Message</Button>
                  <Button size="sm" variant="ghost" disabled={!peer} aria-label={`Enlarge ${r.name}`} onClick={() => setFocus(r.attempt.id)}><Maximize2 /></Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Dialog open={!!focused} onOpenChange={(o) => !o && setFocus(null)}>
        <DialogContent className="sm:max-w-5xl">
          <DialogHeader><DialogTitle>{focused?.name}</DialogTitle><DialogDescription>Live camera and screen.</DialogDescription></DialogHeader>
          {focused && tile(focused, true)}
        </DialogContent>
      </Dialog>

      <Dialog open={!!writing} onOpenChange={(o) => !o && setWriting(null)}>
        <DialogContent>
          <form onSubmit={send} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Message to {people.find((r) => r.attempt.id === writing)?.name}</DialogTitle>
              <DialogDescription>It appears on their screen at once. It is saved in their timeline.</DialogDescription>
            </DialogHeader>
            <Textarea aria-label="Message" maxLength={500} required value={text} onChange={(e) => setText(e.target.value)} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setWriting(null)}>Cancel</Button>
              <Button type="submit" disabled={!text.trim()}>Send</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
