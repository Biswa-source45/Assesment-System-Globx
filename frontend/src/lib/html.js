// Question and exam texts are typed as plain text but stored as HTML (the server sanitises it).
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")

// Plain text becomes paragraphs; text that already contains HTML tags is sent as it is.
export const toHtml = (t) =>
  /<[a-z][\s\S]*>/i.test(t) ? t : t.split(/\n{2,}/).filter((p) => p.trim()).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("")

// The reverse, for editing: simple paragraphs go back to plain text, anything richer stays HTML.
export const fromHtml = (h) =>
  /^(<p>[^<]*(<br>[^<]*)*<\/p>)*$/.test(h || "") ? unesc((h || "").replace(/<\/p><p>/g, "\n\n").replace(/<br>/g, "\n").replace(/<\/?p>/g, "")) : h

// Pictures live inside the stored question text as <img src="data:...">. The editor keeps them apart from the words (a list of pictures
// under the text box), so nobody sees picture code; saving puts them back under the text.
const IMG = /<p>\s*<img\b[^>]*>\s*<\/p>|<img\b[^>]*>/gi
export function splitImages(html) {
  const images = []
  const text = (html || "").replace(IMG, (m) => { const s = /\bsrc="([^"]*)"/i.exec(m); if (s) images.push(s[1]); return "" })
  return { text, images }
}
export const joinImages = (html, images) => html + images.map((src, i) => `<p><img src="${src}" alt="Picture ${i + 1}"></p>`).join("")
