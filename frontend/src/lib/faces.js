// Face detection in the browser with MediaPipe (models and wasm are served from /mediapipe, so no internet is needed).
// The face detector counts faces and gives the box. The face landmarker (loaded only for exams that check where the head points or whether
// the face is covered) gives the head's turn.
import { FaceDetector, FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision"

let detector = null
let landmarker = null
let wasm = null
export const DEFAULT_ZONE = 70  // % of the camera picture the oval covers (the server clamps the exam's value to 40-100)
const files = () => (wasm ??= FilesetResolver.forVisionTasks("/mediapipe/wasm"))

export function loadFaceDetector() {
  detector ??= files()
    .then((f) => FaceDetector.createFromOptions(f, {
      baseOptions: { modelAssetPath: "/mediapipe/face_detector.tflite", delegate: "CPU" },
      runningMode: "VIDEO",
      minDetectionConfidence: 0.5,
    }))
    .catch((e) => { detector = null; throw e })
  return detector
}

export function loadLandmarker() {
  landmarker ??= files()
    .then((f) => FaceLandmarker.createFromOptions(f, {
      baseOptions: { modelAssetPath: "/mediapipe/face_landmarker.task", delegate: "CPU" },
      runningMode: "VIDEO", numFaces: 1, outputFacialTransformationMatrixes: true,
    }))
    .catch((e) => { landmarker = null; throw e })
  return landmarker
}

// Does this exam check where the head points or whether the face is covered? (then the landmarker is needed)
export const usesPose = (cfg) => !!cfg && !!(cfg.hand_on_face || Object.values(cfg.look ?? {}).some((v) => v > 0))

const DEG = 180 / Math.PI

// The faces in the current video frame: {w, h, faces: [{x, y, w, h}]} in video pixels (no faces when the video is not playing).
// With `pose` and exactly one face it adds `pose: {yaw, pitch}` in degrees (yaw: positive = the candidate turned to their own left, negative = right,
// checked on real pictures: the nose moves towards the right of the camera's own, unmirrored frame; pitch: positive = down) or `covered: true` when the detector sees a face that the landmarker cannot (a hand in front of it).
// `strict` (the check-in page) lets a landmarker that cannot start raise an error; during the exam it is skipped, so the face count keeps working.
export async function detectFaces(video, { pose = false, strict = false } = {}) {
  // Test hook, only compiled into the dev server: pretend to be n faces. __faceAt = [x, y] (0 to 1) is where the first face's centre is (the middle by default),
  // __facePose = [yaw, pitch] the head's turn (straight by default), __faceCovered = true a face behind a hand.
  if (import.meta.env.DEV && typeof window.__faceCount === "number") {
    const w = video?.videoWidth || 640, h = video?.videoHeight || 480
    const [cx, cy] = window.__faceAt ?? [0.5, 0.5]
    const faces = Array.from({ length: window.__faceCount }, (_, i) => ({ w: w * 0.26, h: h * 0.38, x: w * (cx + i * 0.3 - 0.13), y: h * (cy - 0.19) }))
    if (!pose || faces.length !== 1) return { w, h, faces }
    return window.__faceCovered ? { w, h, faces, covered: true } : { w, h, faces, pose: { yaw: (window.__facePose ?? [0, 0])[0], pitch: (window.__facePose ?? [0, 0])[1] } }
  }
  const d = await loadFaceDetector()
  if (!video || video.readyState < 2 || !video.videoWidth) return { w: 640, h: 480, faces: [] }
  const w = video.videoWidth, h = video.videoHeight
  const faces = d.detectForVideo(video, performance.now()).detections.filter((x) => x.boundingBox)
    .map(({ boundingBox: b }) => ({ x: b.originX, y: b.originY, w: b.width, h: b.height }))
  const seen = { w, h, faces }
  if (pose && faces.length === 1) {
    try {
      const r = (await loadLandmarker()).detectForVideo(video, performance.now())
      const m = r.facialTransformationMatrixes[0]?.data  // 4x4, column by column: the head's rotation is the first three of each column
      if (!m) seen.covered = true
      else seen.pose = { yaw: Math.atan2(m[8], m[10]) * DEG, pitch: Math.asin(Math.max(-1, Math.min(1, -m[9]))) * DEG }
    } catch (e) { if (strict) throw e }
  }
  return seen
}

// The mean of a few {yaw, pitch}, used as the candidate's own "looking straight at the screen".
export const meanPose = (list) => ({ yaw: list.reduce((s, p) => s + p.yaw, 0) / list.length, pitch: list.reduce((s, p) => s + p.pitch, 0) / list.length })
const KEY = "oap-neutral"  // kept for the browser tab, so the exam page (also after a reload) measures from what the check-in saw
export const getNeutral = () => { try { return JSON.parse(sessionStorage.getItem(KEY)) } catch { return null } }
export const setNeutral = (v) => { try { v ? sessionStorage.setItem(KEY, JSON.stringify(v)) : sessionStorage.removeItem(KEY) } catch { /* the exam still works */ } }

// "none", "many", "hand" (face covered), "off" (the middle of the face is outside the oval), "left", "right", "up", "down" (the head is turned
// further than the exam allows, measured from `neutral`) or "ok". The oval is centred and spans face_zone% of the picture.
export function faceState(seen, cfg = {}, neutral = { yaw: 0, pitch: 0 }) {
  const { w, h, faces } = seen
  if (faces.length === 0) return "none"
  if (faces.length > 1) return "many"
  if (cfg.hand_on_face && seen.covered) return "hand"
  const f = faces[0], zone = cfg.face_zone ?? DEFAULT_ZONE
  const dx = (f.x + f.w / 2 - w / 2) / (w * zone / 200), dy = (f.y + f.h / 2 - h / 2) / (h * zone / 200)
  if (dx * dx + dy * dy > 1) return "off"
  if (seen.pose) {
    const turn = seen.pose.yaw - neutral.yaw, tilt = seen.pose.pitch - neutral.pitch, L = cfg.look ?? {}
    if (L.left && turn > L.left) return "left"
    if (L.right && turn < -L.right) return "right"
    if (L.down && tilt > L.down) return "down"
    if (L.up && tilt < -L.up) return "up"
  }
  return "ok"
}
