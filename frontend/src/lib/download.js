import { api } from "@/lib/api"

// Download a file from the API (it needs the sign-in token, so a plain link cannot do it). The file name comes from the server.
export async function saveFile(path, fallbackName = "download") {
  const r = await api(path, { raw: true })
  const name = /filename="?([^";]+)"?/.exec(r.headers.get("content-disposition") || "")?.[1] || fallbackName
  const a = document.createElement("a")
  a.href = URL.createObjectURL(await r.blob())
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  return name
}
