import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Camera } from "lucide-react"
import { get, post } from "@/lib/api"
import { countFaces, loadFaceDetector } from "@/lib/faces"
import { getCamera, getScreen, screenLive, stopCamera, systemCheck } from "@/lib/media"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"

const STABLE_CHECKS = 3  // consecutive 0.5 s checks with exactly one face before Start is allowed

export default function CheckIn() {
  const { assignmentId } = useParams()
  const navigate = useNavigate()
  const video = useRef(null)
  const started = useRef(false)
  const [item, setItem] = useState(null)
  const [error, setError] = useState("")
  const [cameraOn, setCameraOn] = useState(false)
  const [faces, setFaces] = useState(null)
  const [stable, setStable] = useState(false)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    get("/me/assignments")
      .then((list) => setItem(list.find((x) => x.assignment_id === assignmentId) ?? false))
      .catch((e) => setError(e.message))
    loadFaceDetector().catch(() => {})  // warm up while the candidate reads the rules
    return () => { if (!started.current) stopCamera() }
  }, [assignmentId])

  // Count faces twice a second while the camera is on.
  useEffect(() => {
    if (!cameraOn) return
    let streak = 0
    const id = setInterval(async () => {
      try {
        const n = await countFaces(video.current)
        streak = n === 1 ? streak + 1 : 0
        setFaces(n)
        setStable(streak >= STABLE_CHECKS)
      } catch {
        setError("Face detection could not start. Refresh the page; if it keeps failing, tell the invigilator.")
      }
    }, 500)
    return () => clearInterval(id)
  }, [cameraOn])

  async function enableCamera() {
    setError("")
    try {
      const stream = await getCamera(item?.test.proctoring.live_view)  // with the microphone when the invigilator may talk to the candidate
      video.current.srcObject = stream
      await video.current.play().catch(() => {})
      setCameraOn(true)
    } catch {
      setError("The camera is blocked. Click the camera icon in the address bar, allow access, then try again.")
    }
  }

  if (item === null && !error) return <div className="p-8 text-muted-foreground">Loading...</div>
  if (item === false) return <div className="p-8">Exam not found. <Link className="text-primary underline" to="/exam">Back</Link></div>
  if (!item) return <div className="p-8 text-destructive">{error}</div>

  const cfg = item.test.proctoring
  const needCamera = cfg.enabled && cfg.webcam
  const needScreen = cfg.enabled && cfg.screen_share
  const extraScreen = cfg.enabled && cfg.block_multi_display && window.screen.isExtended === true
  const ready = (!needCamera || (cameraOn && stable)) && (!cfg.enabled || consent) && !extraScreen
  const faceLabel = faces === null ? "Waiting for camera" : faces === 1 ? "1 face detected" : faces === 0 ? "No face detected" : `${faces} faces detected`

  async function start() {
    setBusy(true)
    setError("")
    try {
      // One click does it all. Full screen goes first: it needs this click, while Chrome's share box can take a person several seconds (measured:
      // asked after the box, full screen is refused). Then the screen, with "Entire screen" preselected.
      const full = () => document.documentElement.requestFullscreen().catch(() => {})
      if (cfg.enabled && cfg.fullscreen) await full()
      if (needScreen && !screenLive()) await getScreen()
      if (cfg.enabled && cfg.fullscreen && !document.fullscreenElement) await full()  // the share box may have taken it; the exam asks again if it is still missing
      const r = await post(`/assignments/${assignmentId}/start`, { consent: { accepted: true, text_version: "2026-11" }, system_check: systemCheck() })
      started.current = true
      navigate(`/exam/attempt/${r.attempt_id}`)
    } catch (e) {
      setError(e.message === "not the whole screen" ? "Please share your entire screen, not a window or a tab. Press the button again and keep Entire screen selected."
        : e.name === "NotAllowedError" ? "Screen sharing was cancelled or blocked. Press the button again, keep Entire screen selected and press Share." : e.message)
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-svh bg-muted/40 p-4 md:p-8">
      <div className="mx-auto grid max-w-5xl gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">{item.test.title}</CardTitle>
            <CardDescription>{item.test.duration_min} minutes</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm">
            {item.test.instructions && <div className="prose-sm" dangerouslySetInnerHTML={{ __html: item.test.instructions }} />}
            {cfg.enabled ? (
              <ul className="list-disc space-y-1.5 pl-5">
                {cfg.fullscreen && <li>The exam runs in full screen. You may leave full screen or switch tabs <b>{cfg.tab_switch_limit} times</b>, each with a warning; the next time your exam ends.</li>}
                {cfg.webcam && <li>Keep <b>exactly one face</b> in the camera. After <b>{cfg.face_limit} face warnings</b> your exam ends and your login is locked.</li>}
                {cfg.block_paste && <li>Copy, paste and right-click are disabled.</li>}
                {needScreen && <li>You share your <b>entire screen</b> for the whole exam. Your browser asks you once, when you press the start button: keep <b>Entire screen</b> selected and press <b>Share</b>. If you stop sharing it counts like leaving the window.</li>}
                {cfg.evidence === "video"
                  ? <li>Your camera{needScreen ? " and screen are" : " is"} <b>recorded</b> for the whole exam and the recording is deleted after {cfg.video_retention_days} days.</li>
                  : <li>Pictures of your camera{needScreen ? " and screen are" : " are"} saved during the exam.</li>}
                {cfg.live_view && <li>The invigilator can watch live and may <b>speak to you or send you a message</b>. Please wear <b>headphones</b> so only you hear it.</li>}
                <li>Your answers save automatically. When time is over the exam submits by itself.</li>
              </ul>
            ) : (
              <p>This exam is not proctored.</p>
            )}
            {cfg.enabled && (
              <div className="flex items-start gap-2">
                <Checkbox id="consent" checked={consent} onCheckedChange={(v) => setConsent(v === true)} />
                <Label htmlFor="consent" className="leading-snug">I understand and agree to be monitored by camera{needScreen ? " and screen" : ""}{cfg.evidence === "video" ? ", and recorded," : ""} during this exam.</Label>
              </div>
            )}
            {extraScreen && <Alert variant="destructive" className="p-3">Disconnect the second screen to continue.</Alert>}
            {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
            {item.message && !item.can_start && <Alert className="p-3">{item.message}</Alert>}
            <Button size="lg" disabled={!ready || busy || !item.can_start} onClick={start}>{busy ? "Starting..." : needScreen ? "Accept and start exam" : "Start exam"}</Button>
          </CardContent>
        </Card>

        {needCamera && (
          <Card>
            <CardHeader>
              <CardTitle>Camera check</CardTitle>
              <CardDescription>Sit in good light, facing the camera, alone in the frame.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="aspect-[4/3] overflow-hidden rounded-lg bg-black">
                <video ref={video} muted playsInline className="size-full object-cover" />
              </div>
              {cameraOn ? (
                <Badge data-testid="face-status" variant={faces === 1 ? "default" : "destructive"} className={"w-fit " + (faces === 1 ? "bg-green-600" : "")}>{faceLabel}</Badge>
              ) : (
                <Button variant="outline" onClick={enableCamera}><Camera /> Enable camera</Button>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
