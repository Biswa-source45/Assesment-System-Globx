// The camera (and, when the invigilator may talk to the candidate, the microphone) and the shared screen are opened on the
// check-in page and reused by the exam page (same browser session).
export const media = { stream: null, screen: null }
if (import.meta.env.DEV) window.__media = media  // dev only: lets a browser test simulate a candidate pressing "Stop sharing"

export async function getCamera(withMic = false) {
  if (media.stream?.getVideoTracks().some((t) => t.readyState === "live")) return media.stream
  const video = { width: 640, height: 480 }
  try {
    media.stream = await navigator.mediaDevices.getUserMedia({ video, audio: withMic ? { echoCancellation: true, noiseSuppression: true } : false })
  } catch (e) {
    if (!withMic) throw e
    media.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false })  // no microphone: the candidate can still hear the invigilator
  }
  media.stream.getAudioTracks().forEach((t) => { t.enabled = false })  // the microphone is silent until the invigilator opens a line
  return media.stream
}

// Everything the browser holds open for the exam ends here: camera, microphone and screen.
export function stopCamera() {
  media.stream?.getTracks().forEach((t) => t.stop())
  media.screen?.getTracks().forEach((t) => t.stop())
  media.stream = null
  media.screen = null
}

export const cameraLive = () => !!media.stream?.getVideoTracks().some((t) => t.readyState === "live")

// The whole screen at a low frame rate (an exam is mostly still text). Chrome's own box always appears; the options below only make it open on
// "Entire screen" (they are hints, a person can still pick otherwise). A window or a tab is refused: it would hide the rest of the screen.
export async function getScreen() {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: { ideal: 3, max: 5 }, width: { max: 1280 }, displaySurface: "monitor" }, audio: false,
    monitorTypeSurfaces: "include", selfBrowserSurface: "exclude", surfaceSwitching: "exclude",
  })
  const surface = (import.meta.env.DEV && window.__displaySurface) || stream.getVideoTracks()[0].getSettings().displaySurface  // undefined when the browser does not say; the hook is dev only, for tests
  if (surface && surface !== "monitor") {
    stream.getTracks().forEach((t) => t.stop())
    throw new Error("not the whole screen")
  }
  media.screen = stream
  return stream
}

export const screenLive = () => !!media.screen?.getVideoTracks().some((t) => t.readyState === "live")

// Hints for the proctoring report: extra monitors and virtual machines.
export function systemCheck() {
  let renderer = ""
  try {
    const gl = document.createElement("canvas").getContext("webgl")
    const ext = gl?.getExtension("WEBGL_debug_renderer_info")
    renderer = String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl?.getParameter(gl.RENDERER) || "")
  } catch { /* no webgl */ }
  return {
    camera: cameraLive(),
    displays: window.screen.isExtended === true ? 2 : 1,
    vm_suspected: /vmware|virtualbox|llvmpipe|swiftshader|parallels|hyper-v|microsoft basic render/i.test(renderer),
    renderer,
    browser: navigator.userAgent.slice(0, 200),
  }
}
