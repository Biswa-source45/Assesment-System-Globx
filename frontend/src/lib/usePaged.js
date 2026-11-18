import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"

export const PAGE = 50  // rows per page

// A search box that asks the server only when the person stops typing.
export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

// A long list loaded page by page: the first `size` rows now, the next ones when `more()` is called (components/MoreRows.jsx does that on scroll).
// `path` answers ?limit=&offset= with an array and the number of rows in all in the X-Total-Count header, or with {rows, total, ...the rest} (an exam's
// candidates and results; the rest is returned as `meta`). `params` are its filters: a change starts again, keeping the old rows on screen until the new
// first page is here. An empty path switches it off. Options: size, idKey (the field that tells rows apart), quiet (a poll: no spinner in the corner).
// rows is null until the first page is here. reload() fetches again as many rows as are on screen, so the list keeps its place after an edit.
export function usePaged(path, params = {}, { size = PAGE, idKey = "id", quiet = false } = {}) {
  const [rows, setRows] = useState(null)
  const [total, setTotal] = useState(0)
  const [meta, setMeta] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const latest = useRef(0)   // a newer request makes an older answer stale
  const have = useRef(0)
  const key = JSON.stringify(params)

  const fetchRows = useCallback(async (offset, replace, count) => {
    if (!path) return
    const id = ++latest.current
    const q = new URLSearchParams({ limit: count, offset })
    for (const [k, v] of Object.entries(JSON.parse(key))) if (v !== "" && v != null) q.set(k, v)
    setBusy(true)
    try {
      const r = await api(`${path}?${q}`, { raw: true, quiet })
      const body = await r.json()
      if (id !== latest.current) return
      const list = Array.isArray(body) ? body : body.rows
      setTotal(Array.isArray(body) ? Number(r.headers.get("X-Total-Count")) || list.length : body.total)
      if (!Array.isArray(body)) setMeta(body)
      setRows((old) => {
        if (replace || !old) return list
        const seen = new Set(old.map((x) => x[idKey]))  // a row added meanwhile pushes the others down: never show one twice
        return [...old, ...list.filter((x) => !seen.has(x[idKey]))]
      })
      setError("")
    } catch (e) {
      if (id === latest.current) setError(e.message)
    } finally {
      if (id === latest.current) setBusy(false)
    }
  }, [path, key, idKey, quiet])

  useEffect(() => { fetchRows(0, true, size) }, [fetchRows, size])
  have.current = rows?.length ?? 0
  const more = useCallback(() => { if (!busy) fetchRows(have.current, false, size) }, [busy, fetchRows, size])
  const reload = useCallback(() => fetchRows(0, true, Math.min(500, Math.max(size, have.current))), [fetchRows, size])
  return { rows, total, meta, busy, error, more, reload, done: rows !== null && rows.length >= total }
}
