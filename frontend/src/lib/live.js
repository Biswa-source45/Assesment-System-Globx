// Live view and voice (WebRTC). The server only relays the small messages two browsers need to find each other (see backend/app/api/live.py);
// camera, screen and voice then travel directly between the browsers. The candidate always makes the offer.
import { accessToken, get } from "@/lib/api"

export const CONNECT_WAIT_MS = 15_000  // a tile that has not connected after this long says so
let ice = []  // the connection settings (STUN/TURN), fetched before the WebSocket opens, so no message ever has to wait for them

// A WebSocket to the exam's room that reconnects by itself. `onOpen` runs on every (re)connection.
// Messages are handled strictly one after the other: an offer is fully applied before the connection details that follow it,
// which is what makes the connection details arrive at a connection that is ready for them.
function socket(testId, onMessage, onOpen) {
  let ws, closed = false, timer, chain = Promise.resolve()
  async function open() {
    try { ice = (await get("/live/ice")).iceServers } catch { /* the call also refreshes an expired login; without settings the browser still tries direct */ }  // eslint-disable-line no-empty
    if (closed) return
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/live/${testId}?access_token=${accessToken()}`)
    ws.onopen = () => onOpen?.()
    ws.onmessage = (e) => { chain = chain.then(() => onMessage(JSON.parse(e.data))).catch(() => {}) }  // a bad message must not stop the ones after it
    ws.onclose = () => { if (!closed) timer = setTimeout(open, 3000) }
  }
  open()
  return {
    send: (msg) => ws?.readyState === 1 && ws.send(JSON.stringify(msg)),
    close: () => { closed = true; clearTimeout(timer); ws?.close() },
  }
}

const cap = async (sender, maxBitrate) => {  // keep the video small: many streams share the office Wi-Fi
  try { const p = sender.getParameters(); p.encodings = p.encodings?.length ? p.encodings : [{}]; p.encodings[0].maxBitrate = maxBitrate; await sender.setParameters(p) } catch { /* the browser decides */ }  // eslint-disable-line no-empty
}

// Candidate side. Offers the camera, the screen and a silent microphone to every examiner in the room.
// The camera may be missing (an exam without the camera check): the screen alone is then offered, and the examiner can still speak to the candidate.
// onTalk(true|false): an invigilator opened or closed a line to this candidate. onMessage(text): a written message.
export function startPublishing({ testId, camera, screen, onTalk, onMessage }) {
  const peers = new Map()  // examiner id -> { pc, audio, tries }
  const mic = camera?.getAudioTracks()[0]
  let net, stopped = false

  async function offerTo(id, tries = 0) {
    peers.get(id)?.pc.close()
    const pc = new RTCPeerConnection({ iceServers: ice })
    const peer = { pc, audio: new Audio(), tries }
    peers.set(id, peer)
    pc.onicecandidate = (e) => e.candidate && net.send({ type: "ice", to: id, candidate: e.candidate })
    pc.ontrack = (e) => { peer.audio.srcObject = new MediaStream([e.track]); peer.audio.play().catch(() => {}) }  // the invigilator's voice
    // A connection that fails (or stays broken for 10 s) is offered again, a few times, instead of being given up.
    let waiting
    pc.onconnectionstatechange = () => {
      clearTimeout(waiting)
      const state = pc.connectionState
      if (state === "connected") peer.tries = 0
      const retry = () => { if (!stopped && peers.get(id) === peer && peer.tries < 5) { pc.close(); offerTo(id, peer.tries + 1) } }
      if (state === "failed") setTimeout(retry, 2000)
      else if (state === "disconnected") waiting = setTimeout(retry, 10_000)
    }
    const senders = []
    if (camera) senders.push([pc.addTrack(camera.getVideoTracks()[0], camera), 100_000])
    if (screen) senders.push([pc.addTrack(screen.getVideoTracks()[0], screen), 200_000])
    const voice = pc.addTransceiver("audio", { direction: "sendrecv", streams: camera ? [camera] : [] })  // one line both ways, silent until a talk starts
    if (mic) voice.sender.replaceTrack(mic)
    await pc.setLocalDescription(await pc.createOffer())
    senders.forEach(([sender, bitrate]) => cap(sender, bitrate))
    net.send({ type: "offer", to: id, sdp: pc.localDescription.sdp, streams: { camera: camera?.id, screen: screen?.id } })
  }

  function drop(id) {
    peers.get(id)?.pc.close()
    peers.delete(id)
    if (mic) mic.enabled = false
    onTalk(false)
  }

  net = socket(testId, async (m) => {
    if (m.type === "examiners") { for (const id of m.ids) await offerTo(id) }
    else if (m.type === "examiner") await offerTo(m.id)
    else if (m.type === "answer") peers.get(m.from)?.pc.setRemoteDescription({ type: "answer", sdp: m.sdp }).catch(() => {})
    else if (m.type === "ice") peers.get(m.from)?.pc.addIceCandidate(m.candidate).catch(() => {})
    else if (m.type === "examiner-left") drop(m.id)
    else if (m.type === "talk-start") { if (mic) mic.enabled = true; onTalk(true) }
    else if (m.type === "talk-stop") { if (mic) mic.enabled = false; onTalk(false) }
    else if (m.type === "message") onMessage(m.text)
  })

  return {
    stop() { stopped = true; net.close(); peers.forEach((p) => p.pc.close()); peers.clear(); if (mic) mic.enabled = false },
  }
}

// Examiner side. Keeps one connection per candidate and reports changes through onChange({ peers, talking }).
// peers: [{ id, name, state, camera: MediaStream | null, screen: MediaStream | null }]; talking: { candidateId: examinerId }.
// state: connecting | connected | disconnected | failed | unreachable (nothing connected within CONNECT_WAIT_MS). A stream exists as soon as the
// offer is read, long before pictures can flow, so only state === "connected" means the tile is live.
export class LiveViewer {
  constructor({ testId, onChange }) {
    this.onChange = onChange
    this.peers = new Map()  // candidate id -> { name, camera, screen, pc, audio, voice }
    this.talking = {}
    this.me = null
    this.net = socket(testId, (m) => this.handle(m))
  }

  emit() {
    this.onChange({ peers: [...this.peers].map(([id, p]) => ({ id, name: p.name, state: p.state ?? "connecting", camera: p.camera ?? null, screen: p.screen ?? null })), talking: { ...this.talking } })
  }

  async handle(m) {
    if (m.type === "peers") {
      this.peers.forEach((p) => { p.pc?.close(); clearTimeout(p.timer) })  // a reconnection: the old lines are gone
      this.me = m.you
      this.talking = m.talking
      this.peers = new Map(m.peers.map((p) => [p.id, { name: p.name }]))
    } else if (m.type === "peer") {
      this.peers.set(m.id, { ...(this.peers.get(m.id) ?? {}), name: m.name })
    } else if (m.type === "peer-left") {
      clearTimeout(this.peers.get(m.id)?.timer)
      this.peers.get(m.id)?.pc?.close()
      this.peers.delete(m.id)
    } else if (m.type === "talking") {
      if (m.by) this.talking[m.id] = m.by; else delete this.talking[m.id]
    } else if (m.type === "busy") {
      this.release(m.id)
      this.onBusy?.(m.id)
    } else if (m.type === "offer") {
      await this.answer(m)
    } else if (m.type === "ice") {
      const peer = this.peers.get(m.from)
      if (peer?.pc?.remoteDescription) peer.pc.addIceCandidate(m.candidate).catch(() => {})
      else if (peer) (peer.early ??= []).push(m.candidate)  // arrived before the offer: kept for when the connection exists
    }
    this.emit()
  }

  async answer({ from, sdp, streams }) {
    const peer = this.peers.get(from) ?? {}
    peer.pc?.close()
    clearTimeout(peer.timer)
    peer.camera = peer.screen = null
    const pc = new RTCPeerConnection({ iceServers: ice })
    Object.assign(peer, { pc, audio: new Audio(), state: "connecting" })
    this.peers.set(from, peer)
    peer.timer = setTimeout(() => { if (peer.state !== "connected") { peer.state = "unreachable"; this.emit() } }, CONNECT_WAIT_MS)
    pc.onconnectionstatechange = () => {
      if (pc !== peer.pc) return  // an older connection closing
      peer.state = pc.connectionState === "new" ? "connecting" : pc.connectionState
      if (peer.state === "connected") clearTimeout(peer.timer)
      this.emit()
    }
    pc.onicecandidate = (e) => e.candidate && this.net.send({ type: "ice", to: from, candidate: e.candidate })
    pc.ontrack = (e) => {
      if (e.track.kind === "audio") { peer.audio.srcObject = new MediaStream([e.track]); peer.audio.muted = true; return }  // the candidate's voice, heard only during a talk
      const stream = e.streams[0]
      if (stream?.id === streams?.screen) peer.screen = stream; else peer.camera = stream
      this.emit()
    }
    await pc.setRemoteDescription({ type: "offer", sdp })
    for (const c of peer.early?.splice(0) ?? []) pc.addIceCandidate(c).catch(() => {})
    peer.voice = pc.getTransceivers().find((t) => t.receiver.track.kind === "audio")
    if (peer.voice) peer.voice.direction = "sendrecv"  // so the examiner's voice can go back on the same line
    await pc.setLocalDescription(await pc.createAnswer())
    this.net.send({ type: "answer", to: from, sdp: pc.localDescription.sdp })
  }

  // Open a line to one candidate (must be called from a click: the browser asks for the microphone and allows sound).
  async talk(id) {
    const peer = this.peers.get(id)
    if (!peer?.voice) return
    this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    await peer.voice.sender.replaceTrack(this.mic.getAudioTracks()[0])
    peer.audio.muted = false
    peer.audio.play().catch(() => {})
    this.net.send({ type: "talk-start", to: id })
  }

  release(id) {
    const peer = this.peers.get(id)
    peer?.voice?.sender.replaceTrack(null).catch(() => {})
    if (peer?.audio) peer.audio.muted = true
    this.mic?.getTracks().forEach((t) => t.stop())
    this.mic = null
  }

  stopTalk(id) {
    this.release(id)
    this.net.send({ type: "talk-stop", to: id })
  }

  message(id, text) { this.net.send({ type: "message", to: id, text }) }

  stop() {
    this.net.close()
    this.peers.forEach((p) => { p.pc?.close(); clearTimeout(p.timer) })
    this.mic?.getTracks().forEach((t) => t.stop())
  }
}
