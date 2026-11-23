import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Camera } from "lucide-react"
import { get, post } from "@/lib/api"
import { detectFaces, faceState, loadFaceDetector, loadLandmarker, meanPose, setNeutral, usesPose } from "@/lib/faces"
import FaceGuide from "@/components/FaceGuide"
import { getCamera, getScreen, screenLive, stopCamera, systemCheck, wrongBrowser } from "@/lib/media"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Loading } from "@/components/Spinner"

const STABLE_CHECKS = 3  // consecutive 0.5 s checks with exactly one face before Start is allowed

export default function CheckIn() {
  const { assignmentId } = useParams()
  const navigate = useNavigate()
  const video = useRef(null)
  const started = useRef(false)
  const [item, setItem] = useState(null)
  const [error, setError] = useState("")
  const [cameraOn, setCameraOn] = useState(false)
  const [face, setFace] = useState(null)  // {seen: {w, h, faces}, state: ok | none | many | off}
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
  useEffect(() => { if (item && usesPose(item.test.proctoring)) loadLandmarker().catch(() => {}) }, [item])

  // Count faces twice a second while the camera is on.
  useEffect(() => {
    if (!cameraOn) return
    const rules = item.test.proctoring, rulesOn = usesPose(rules)
    let streak = 0, neutral = null, poses = []
    setNeutral(null)  // "looking straight" is measured afresh, from the first good looks
    const id = setInterval(async () => {
      try {
        const seen = await detectFaces(video.current, { pose: rulesOn, strict: true })
        let state = faceState(seen, { ...rules, look: undefined })  // the count, a covered face, the oval
        if (state === "ok" && seen.pose) {
          if (!neutral) {
            poses = [...poses, seen.pose].slice(-STABLE_CHECKS)
            if (poses.length === STABLE_CHECKS) {
              const m = meanPose(poses)
              if (Math.abs(m.yaw) > 25 || Math.abs(m.pitch) > 25) { state = "straight"; poses = [] }  // not a straight look at the screen
              else { neutral = m; setNeutral(m) }
            }
          }
          if (neutral) state = faceState(seen, rules, neutral)
        } else poses = []
        streak = state === "ok" ? streak + 1 : 0
        setFace({ seen, state })
        setStable(streak >= STABLE_CHECKS)
      } catch {
        setError("Face detection could not start. Refresh the page; if it keeps failing, tell the invigilator.")
      }
    }, 500)
    return () => clearInterval(id)
  }, [cameraOn, item])

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

  if (item === null && !error) return <div className="p-8"><Loading /></div>
  if (item === false) return <div className="p-8">Exam not found. <Link className="text-primary underline" to="/exam">Back</Link></div>
  if (!item) return <div className="p-8 text-destructive">{error}</div>

  const cfg = item.test.proctoring
  const needCamera = cfg.enabled && cfg.webcam
  const needScreen = cfg.enabled && cfg.screen_share
  const extraScreen = cfg.enabled && cfg.block_multi_display && window.screen.isExtended === true
  const ready = (!needCamera || (cameraOn && stable)) && (!cfg.enabled || consent) && !extraScreen
  const faceLabel = !face ? "Waiting for camera" : {
    ok: "1 face detected", off: "Move your face into the oval", none: "No face detected", many: `${face.seen.faces.length} faces detected`,
    hand: "Face covered: take your hand away", straight: "Look straight at the screen", left: "Looking left: look at the screen",
    right: "Looking right: look at the screen", up: "Looking up: look at the screen", down: "Looking down: look at the screen",
  }[face.state]
  const dirs = ["left", "right", "up", "down"].filter((d) => cfg.look?.[d] > 0)

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
    <div className="min-h-svh bg-muted/40 p-4 md:h-svh md:overflow-hidden md:p-8">
      <div className="mx-auto grid max-w-5xl gap-6 md:h-full md:grid-cols-2 md:grid-rows-[minmax(0,1fr)]">
        <Card className="md:min-h-0">
          <CardHeader className="shrink-0">
            <CardTitle className="text-xl">{item.test.title}</CardTitle>
            <CardDescription>{item.test.duration_min} minutes</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 text-sm md:min-h-0 md:flex-1 md:content-start md:overflow-y-auto" data-testid="rules-scroll">
            <Alert variant={wrongBrowser() ? "destructive" : undefined} className="p-3" data-testid="browser-note">
              {wrongBrowser() ? "You are not using Google Chrome or Microsoft Edge. Please open this exam in one of them: in other browsers (Firefox, Brave and the like) it may not start." : "Use Google Chrome or Microsoft Edge for this exam. Other browsers (Firefox, Brave and the like) may not work."}
            </Alert>
            {item.test.instructions && <div className="q-html" data-testid="exam-instructions" dangerouslySetInnerHTML={{ __html: item.test.instructions }} />}
            {item.test.min_question_seconds > 0 && <p>Each question stays on screen for at least <b>{item.test.min_question_seconds} seconds</b> before you can move on, so please read it.</p>}
            {cfg.enabled ? (
              <ul className="list-disc space-y-1.5 pl-5">
                {cfg.fullscreen && <li>The exam runs in full screen. You may leave full screen or switch tabs <b>{cfg.tab_switch_limit} times</b>, each with a warning; the next time your exam ends.</li>}
                {cfg.webcam && <li>Keep <b>exactly one face</b>, inside the <b>green oval</b>, in the camera. After <b>{cfg.face_limit} face warnings</b> your exam ends and your login is locked.</li>}
                {cfg.webcam && (dirs.length > 0 || cfg.hand_on_face) && <li>Look at the screen{dirs.length > 0 && <>: do not turn your head <b>{dirs.join(", ")}</b></>}{cfg.hand_on_face ? <>{dirs.length > 0 ? "; " : ": "}do not cover your face with your hand</> : ""}. These count as face warnings too.</li>}
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
          </CardContent>
          <div className="grid shrink-0 gap-3 border-t px-4 pt-4 text-sm">
            {cfg.enabled && (
              <div className="flex items-start gap-2">
                <Checkbox id="consent" checked={consent} onCheckedChange={(v) => setConsent(v === true)} />
                <Label htmlFor="consent" className="leading-snug">I understand and agree to be monitored by camera{needScreen ? " and screen" : ""}{cfg.evidence === "video" ? ", and recorded," : ""} during this exam.</Label>
              </div>
            )}
            {extraScreen && <Alert variant="destructive" className="p-3">Disconnect the second screen to continue.</Alert>}
            {error && <Alert variant="destructive" className="p-3">{error}</Alert>}
            {item.message && !item.can_start && <Alert className="p-3">{item.message}</Alert>}
            <Button size="lg" disabled={!ready || busy || !item.can_start} onClick={start} loading={busy}>{busy ? "Starting..." : needScreen ? "Accept and start exam" : "Start exam"}</Button>
          </div>
        </Card>

        {needCamera && (
          <Card className="md:max-h-full md:self-start md:overflow-y-auto">
            <CardHeader>
              <CardTitle>Camera check</CardTitle>
              <CardDescription>Sit in good light, alone, and keep your face inside the green oval.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <FaceGuide videoRef={video} seen={face?.seen} state={face?.state} zone={cfg.face_zone} className="rounded-lg" />
              {cameraOn ? (
                <Badge data-testid="face-status" variant={face?.state === "ok" ? "default" : "destructive"} className={"w-fit " + (face?.state === "ok" ? "bg-green-600" : "")}>{faceLabel}</Badge>
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
