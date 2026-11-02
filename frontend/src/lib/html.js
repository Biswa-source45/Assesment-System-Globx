// Question and exam texts are typed as plain text but stored as HTML (the server sanitises it).
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")

// Plain text becomes paragraphs; text that already contains HTML tags is sent as it is.
export const toHtml = (t) =>
  /<[a-z][\s\S]*>/i.test(t) ? t : t.split(/\n{2,}/).filter((p) => p.trim()).map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("")

// The reverse, for editing: simple paragraphs go back to plain text, anything richer stays HTML.
export const fromHtml = (h) =>
  /^(<p>[^<]*(<br>[^<]*)*<\/p>)*$/.test(h || "") ? unesc((h || "").replace(/<\/p><p>/g, "\n\n").replace(/<br>/g, "\n").replace(/<\/?p>/g, "")) : h
