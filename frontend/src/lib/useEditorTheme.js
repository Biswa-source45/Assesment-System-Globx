import { useState } from "react"

const KEY = "editor.theme"

// The code editor is dark by default. Anyone can switch to light, and the choice is remembered in this browser.
export function useEditorTheme() {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem(KEY) !== "light" } catch { return true }
  })
  const toggle = () => {
    const next = !dark
    setDark(next)
    try { localStorage.setItem(KEY, next ? "dark" : "light") } catch { /* storage blocked: the choice lasts until reload */ }
  }
  return [dark, toggle]
}
