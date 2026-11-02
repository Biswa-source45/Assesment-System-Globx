// Face counting in the browser with MediaPipe (model and wasm are served from /mediapipe, so no internet is needed).
import { FaceDetector, FilesetResolver } from "@mediapipe/tasks-vision"

let detector = null

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

// Returns the number of faces in the current video frame (0 when the video is not playing).
export async function countFaces(video) {
  // Test hook, only compiled into the dev server: lets Playwright pretend to be 0, 1 or 2 faces.
  if (import.meta.env.DEV && typeof window.__faceCount === "number") return window.__faceCount
  const d = await loadFaceDetector()
  if (!video || video.readyState < 2 || !video.videoWidth) return 0
  return d.detectForVideo(video, performance.now()).detections.length
}
