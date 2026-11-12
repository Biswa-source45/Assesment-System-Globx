// A picture chosen or pasted by a person becomes a data URI the server accepts: at most 1200 px on the long side, PNG (JPEG if that is still over ~0.9 MB).
const LIMIT = 900_000

export async function fileToDataUrl(file) {
  if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) throw new Error("Choose a PNG, JPEG, GIF or WEBP picture.")
  const bmp = await createImageBitmap(file).catch(() => { throw new Error("This picture could not be read.") })
  for (let side = 1200; side >= 300; side = Math.round(side * 0.7)) {
    const k = Math.min(1, side / Math.max(bmp.width, bmp.height))
    const c = document.createElement("canvas")
    c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k))
    const ctx = c.getContext("2d")
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height)  // a see-through picture is put on white
    ctx.drawImage(bmp, 0, 0, c.width, c.height)
    for (const url of [c.toDataURL("image/png"), c.toDataURL("image/jpeg", 0.8)]) if (url.length <= LIMIT) return url
  }
  throw new Error("This picture is too large. Use a smaller one.")
}

// A screenshot pasted into a text box: returns the picture file, or null for ordinary text.
export const pastedImage = (e) => [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/")) ?? null
