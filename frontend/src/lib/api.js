// Small fetch client: JWT access token + rotating refresh token, JSON and file helpers.
const BASE = "/api/v1"
let tokens = (() => {
  try { return JSON.parse(localStorage.getItem("oap.tokens") || "null") } catch { return null }
})()
let refreshing = null

export function setTokens(t) {
  tokens = t ? { access_token: t.access_token, refresh_token: t.refresh_token } : null
  try { t ? localStorage.setItem("oap.tokens", JSON.stringify(tokens)) : localStorage.removeItem("oap.tokens") } catch { /* storage blocked */ }
}
export const hasTokens = () => !!tokens
export const accessToken = () => tokens?.access_token
export const refreshToken = () => tokens?.refresh_token

// How many requests are waiting for the server: the round spinner in the corner (components/Spinner.jsx) shows while it is above 0.
// A request that only keeps something up to date (a poll, a picture) is sent with { quiet: true } and is not counted.
let waiting = 0
const watchers = new Set()
const count = (n) => { waiting += n; watchers.forEach((f) => f()) }
export const watchRequests = (f) => { watchers.add(f); return () => watchers.delete(f) }
export const requestsWaiting = () => waiting

export class ApiError extends Error {
  constructor(status, detail) {
    const msg = typeof detail === "string" ? detail : detail?.message || (detail?.errors ? detail.errors.join("; ") : JSON.stringify(detail))
    super(msg)
    this.status = status
    this.detail = detail
  }
}

async function refresh() {
  if (!tokens?.refresh_token) return false
  refreshing ??= fetch(BASE + "/auth/refresh", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  })
    .then(async (r) => { if (!r.ok) { setTokens(null); return false } setTokens(await r.json()); return true })
    .catch(() => false)
    .finally(() => { setTimeout(() => { refreshing = null }, 0) })
  return refreshing
}

export async function api(path, opts = {}, retry = true) {
  if (opts.quiet) return send(path, opts, retry)
  count(1)
  try { return await send(path, opts, retry) } finally { count(-1) }
}

async function send(path, { method, body, form, raw, signal } = {}, retry = true) {
  const headers = {}
  if (tokens?.access_token) headers.Authorization = "Bearer " + tokens.access_token
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body) }
  const r = await fetch(BASE + path, { method: method || (payload ? "POST" : "GET"), headers, body: payload, signal })
  if (r.status === 401 && retry && tokens?.refresh_token && !path.startsWith("/auth/login")) {
    if (await refresh()) return send(path, { method, body, form, raw, signal }, false)
  }
  if (raw) {
    if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => null))?.detail ?? r.statusText)
    return r
  }
  const text = await r.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!r.ok) throw new ApiError(r.status, data?.detail ?? data ?? r.statusText)
  return data
}

export const get = (p, opts) => api(p, opts)
export const post = (p, body = {}) => api(p, { method: "POST", body })
export const put = (p, body = {}) => api(p, { method: "PUT", body })
export const del = (p) => api(p, { method: "DELETE" })
