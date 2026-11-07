import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { startPublishing } from "@/lib/live"
import { getScreen, media, screenLive } from "@/lib/media"
import { Recorder } from "@/lib/recorder"

const GRACE_MS = 30_000  // after a page reload the browser asks for the screen again: this long before it counts as stopping the share

// Everything the exam page does beyond the camera for the exam's evidence, driven by the exam's settings (cfg):
// the shared screen (and what happens when it stops), video of the whole exam, the live view for the invigilator, and the
// invigilator's voice and messages. Call begin() once the camera is on and stop() when the exam is over.
export function useEvidence({ st, cfg, attemptId, proctorRef }) {
  const screenVideo = useRef(null)  // a hidden video showing the shared screen, for the screen pictures
  const running = useRef({ recorders: [], publisher: null, grace: null })
  const [screenNeeded, setScreenNeeded] = useState(false)
  const [talk, setTalk] = useState(false)
  const [message, setMessage] = useState("")

  const proctor = () => proctorRef.current

  async function stopStreams() {
    const r = running.current
    r.publisher?.stop()
    r.publisher = null
    const recorders = r.recorders
    r.recorders = []
    await Promise.all(recorders.map((x) => x.stop()))
  }

  // Video of the whole exam and the live view start (again) from whatever is shared now.
  function startStreams(screen) {
    stopStreams()
    const r = running.current
    if (cfg.evidence === "video") {
      if (media.stream) r.recorders.push(new Recorder({ attemptId, kind: "webcam", stream: new MediaStream(media.stream.getVideoTracks()), bitsPerSecond: 120_000 }))
      if (screen) r.recorders.push(new Recorder({ attemptId, kind: "screen", stream: screen, bitsPerSecond: 200_000 }))
      r.recorders.forEach((x) => x.start())
    }
    if (cfg.live_view && (media.stream || screen)) r.publisher = startPublishing({ testId: st.test.id, camera: media.stream, screen, onTalk: setTalk, onMessage: setMessage })
  }

  function attachScreen(stream) {
    clearTimeout(running.current.grace)
    screenVideo.current.srcObject = stream
    screenVideo.current.play().catch(() => {})
    stream.getVideoTracks()[0].addEventListener("ended", () => {  // the candidate pressed "Stop sharing"
      proctor()?.event("screen_share_stopped")
      proctor()?.flush()
      setScreenNeeded(true)
    })
  }

  function begin() {
    const screen = cfg.screen_share && screenLive() ? media.screen : null
    if (screen) attachScreen(screen)
    else if (cfg.screen_share) {  // the page was reloaded: share again, or it counts after a short grace
      setScreenNeeded(true)
      running.current.grace = setTimeout(() => { proctor()?.event("screen_share_stopped"); proctor()?.flush() }, GRACE_MS)
    }
    startStreams(screen)
  }

  async function shareAgain() {
    try {
      const screen = await getScreen()
      attachScreen(screen)
      setScreenNeeded(false)
      startStreams(screen)
    } catch (e) {
      toast.error(e.message === "not the whole screen" ? "Please share your entire screen, not a window or a tab." : "Screen sharing was cancelled. Try again.")
    }
  }

  useEffect(() => () => { clearTimeout(running.current.grace); stopStreams() }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  return { screenVideo, screenNeeded, talk, message, setMessage, begin, shareAgain, stop: () => { clearTimeout(running.current.grace); return stopStreams() } }
}
