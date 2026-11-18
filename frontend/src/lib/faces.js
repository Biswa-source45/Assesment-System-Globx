// Face detection in the browser with MediaPipe (model and wasm are served from /mediapipe, so no internet is needed).
import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision"

let detector = null
export const DEFAULT_ZONE = 70  // % of the camera picture the oval covers (the server clamps the exam's value to 40-100)

export function loadFaceDetector() {
  detector ??= FilesetResolver.forVisionTasks("/mediapipe/wasm")
    .then((files) => FaceDetector.createFromOptions(files, {
      baseOptions: { modelAssetPath: "/mediapipe/face_detector.tflite", delegate: "CPU" },
      runningMode: "VIDEO",
      minDetectionConfidence: 0.5,
    }))
    .catch((e) => { detector = null; throw e })
  return detector
}

// The faces in the current video frame: {w, h, faces: [{x, y, w, h}]} in video pixels (no faces when the video is not playing).
export async function detectFaces(video) {
  // Test hook, only compiled into the dev server: pretend to be n faces. __faceAt = [x, y] (0 to 1) is where the first face's centre is (the middle by default).
  if (import.meta.env.DEV && typeof window.__faceCount === "number") {
    const w = video?.videoWidth || 640, h = video?.videoHeight || 480
    const [cx, cy] = window.__faceAt ?? [0.5, 0.5]
    return { w, h, faces: Array.from({ length: window.__faceCount }, (_, i) => ({ w: w * 0.26, h: h * 0.38, x: w * (cx + i * 0.3 - 0.13), y: h * (cy - 0.19) })) }
  }
  const d = await loadFaceDetector()
  if (!video || video.readyState < 2 || !video.videoWidth) return { w: 640, h: 480, faces: [] }
  const w = video.videoWidth, h = video.videoHeight
  const faces = d.detectForVideo(video, performance.now()).detections.filter((x) => x.boundingBox)
    .map(({ boundingBox: b }) => ({ x: b.originX, y: b.originY, w: b.width, h: b.height }))
  return { w, h, faces }
}

// "none", "many", "off" (the middle of the face is outside the oval) or "ok". The oval is centred and spans zone% of the picture.
export function faceState({ w, h, faces }, zone = DEFAULT_ZONE) {
  if (faces.length === 0) return "none"
  if (faces.length > 1) return "many"
  const f = faces[0]
  const dx = (f.x + f.w / 2 - w / 2) / (w * zone / 200), dy = (f.y + f.h / 2 - h / 2) / (h * zone / 200)
  return dx * dx + dy * dy > 1 ? "off" : "ok"
}
