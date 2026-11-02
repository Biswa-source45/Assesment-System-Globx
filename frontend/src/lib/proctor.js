// Proctoring client. Watches the browser and the camera, reports to the server, and tells the page what to do.
// Server rules (backend/app/services/proctoring.py): tab/fullscreen leaves over the limit terminate the exam;
// the face-limit-th face incident terminates and bans. The server decides; this class only reports.
import { api } from "@/lib/api"
import { cameraLive } from "@/lib/media"
import { countFaces } from "@/lib/faces"

export class Proctor {
  // onResult receives server answers ({action: warn | force_submit | ban, message, ...}) and {action: "fullscreen_required"}
  // onFaces receives the current face count (null while unknown) for the on-screen indicator
  constructor({ attemptId, cfg, video, onResult, onFaces }) {
    Object.assign(this, { attemptId, cfg, video, onResult, onFaces })
    this.queue = []
    this.timers = []
    this.hiddenAt = 0
    this.badSince = 0
    this.reported = false
    this.faces = null
    this.running = false
  }

  event(type, duration_ms = 0, payload = {}) {
    if (this.running) this.queue.push({ type, duration_ms, payload, started_at: new Date().toISOString() })
  }

  start() {
    if (this.running) return
    this.running = true
    const on = (target, name, fn, capture) => {
      target.addEventListener(name, fn, capture)
      this.timers.push(() => target.removeEventListener(name, fn, capture))
    }
    on(document, "visibilitychange", () => (document.hidden ? this.leave() : this.back()))
    on(window, "blur", () => this.leave())
    on(window, "focus", () => this.back())
    on(document, "fullscreenchange", () => {
      if (this.cfg.fullscreen && !document.fullscreenElement) {
        this.event("fs_exit")
        this.flush()
        this.onResult({ action: "fullscreen_required" })
      }
    })
    if (this.cfg.block_paste) {
      const block = (name, type) => on(document, name, (e) => { e.preventDefault(); if (type) this.event(type) }, true)
      block("copy", "copy")
      block("cut", "copy")
      block("paste", "paste")
      block("contextmenu")
      block("dragstart")
      block("drop")
    }
    const every = (ms, fn) => { const id = setInterval(fn, ms); this.timers.push(() => clearInterval(id)) }
    every(3000, () => this.flush())
    if (this.cfg.webcam) {
      every(500, () => this.watchFace())
      every(Math.max(5, this.cfg.snapshot_seconds || 15) * 1000, () => this.snapshot())
      const first = setTimeout(() => this.snapshot(), 4000)
      this.timers.push(() => clearTimeout(first))
    }
  }

  stop() {
    this.running = false
    this.timers.forEach((undo) => undo())
    this.timers = []
  }

  leave() { if (!this.hiddenAt) this.hiddenAt = Date.now() }

  back() {
    if (!this.hiddenAt) return
    const d = Date.now() - this.hiddenAt
    this.hiddenAt = 0
    if (d >= 1000) { this.event("tab_blur", d); this.flush() }  // under 1 s is ignored, same as the server
  }

  async flush() {
    if (!this.queue.length) return
    const events = this.queue.splice(0)
    try {
      this.onResult(await api(`/attempts/${this.attemptId}/proctor/events`, { method: "POST", body: { events } }))
    } catch {
      this.queue.unshift(...events)  // retry on the next tick
    }
  }

  // An incident is one continuous stretch of "not exactly one face" lasting at least face_min_seconds; reported once.
  async watchFace() {
    if (this.busy) return
    this.busy = true
    try {
      const n = cameraLive() ? await countFaces(this.video) : 0  // a stopped camera counts as no face
      this.faces = n
      this.onFaces?.(n)
      const now = Date.now()
      if (n === 1) { this.badSince = 0; this.reported = false; return }
      this.badSince ||= now
      if (!this.reported && now - this.badSince >= (this.cfg.face_min_seconds || 3) * 1000) {
        this.reported = true
        this.event(n > 1 ? "multi_face" : "face_missing", now - this.badSince)
        this.flush()
      }
    } catch { /* detector not ready yet */ } finally { this.busy = false }
  }

  snapshot() {
    const v = this.video
    if (!v?.videoWidth) return
    const c = document.createElement("canvas")
    c.width = 320
    c.height = Math.round(320 * v.videoHeight / v.videoWidth)
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height)
    c.toBlob(async (blob) => {
      if (!blob) return
      const form = new FormData()
      form.append("kind", "webcam")
      if (this.faces !== null) form.append("faces", String(this.faces))
      form.append("image", blob, "cam.jpg")
      try { this.onResult(await api(`/attempts/${this.attemptId}/proctor/snapshot`, { method: "POST", form })) } catch { /* evidence only */ }
    }, "image/jpeg", 0.7)
  }
}
