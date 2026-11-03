import { api } from "@/lib/api"

const PIECE_MS = 10_000
const GIVE_UP = [403, 404, 410, 413, 422, 423]  // the server will never take this piece: stop trying

// Records one stream and sends it to the server in 10-second pieces, in order. A piece stays in the queue until the server has it,
// so a short network drop loses nothing. One Recorder is one file on the server; a page reload makes a new Recorder and a new file.
export class Recorder {
  constructor({ attemptId, kind, stream, bitsPerSecond }) {
    Object.assign(this, { attemptId, kind, stream, bitsPerSecond })
    this.part = Date.now().toString(36)
    this.seq = 0
    this.queue = []
    this.sending = false
    this.retry = null
  }

  start() {
    const mimeType = ["video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m))
    this.rec = new MediaRecorder(this.stream, { mimeType, videoBitsPerSecond: this.bitsPerSecond })
    this.rec.ondataavailable = (e) => {
      if (!e.data.size) return
      this.queue.push({ seq: this.seq++, blob: e.data })
      this.drain()
    }
    this.rec.start(PIECE_MS)
  }

  async drain() {
    if (this.sending) return
    this.sending = true
    while (this.queue.length) {
      const { seq, blob } = this.queue[0]
      const form = new FormData()
      form.append("piece", blob, "piece.webm")
      try {
        await api(`/attempts/${this.attemptId}/recording/${this.kind}?part=${this.part}&seq=${seq}`, { method: "POST", form })
        this.queue.shift()
      } catch (e) {
        if (GIVE_UP.includes(e.status)) { this.queue.shift(); continue }
        clearTimeout(this.retry)
        this.retry = setTimeout(() => this.drain(), 3000)  // offline: try again soon
        break
      }
    }
    this.sending = false
  }

  // Stop recording and give the last pieces a few seconds to reach the server.
  async stop() {
    clearTimeout(this.retry)
    if (this.rec && this.rec.state !== "inactive") {
      await new Promise((done) => { this.rec.onstop = done; this.rec.stop() })  // the last piece arrives as a final dataavailable
    }
    const until = Date.now() + 8000
    while ((this.queue.length || this.sending) && Date.now() < until) {
      this.drain()
      await new Promise((r) => setTimeout(r, 200))
    }
  }
}
