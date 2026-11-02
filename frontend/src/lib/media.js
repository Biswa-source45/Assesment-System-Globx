// The camera stream is opened on the check-in page and reused by the exam page (same browser session).
export const media = { stream: null }

export async function getCamera() {
  if (media.stream?.getVideoTracks().some((t) => t.readyState === "live")) return media.stream
  media.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false })
  return media.stream
}

export function stopCamera() {
  media.stream?.getTracks().forEach((t) => t.stop())
  media.stream = null
}

export const cameraLive = () => !!media.stream?.getVideoTracks().some((t) => t.readyState === "live")

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
