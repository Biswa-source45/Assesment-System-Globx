// Real browsers during a load test: a few candidates take the small "Browser Exam" while the scripts load the server, and an examiner opens the real pages.
// It measures how long the real screens take and saves screenshots for the report (results/<run>/screens/). Needs the frontend's Playwright (npm install done there).
//
//   node browsers.mjs candidates [--run LT-xxxx] [--host http://127.0.0.1:8001]     the real candidate screens, one browser each
//   node browsers.mjs staff      [--run LT-xxxx] [--host ...]                        the examiner's pages (monitor, results, analytics, bank, users)
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const { chromium } = createRequire(import.meta.url)(path.join(here, "..", "frontend", "node_modules", "@playwright", "test"))

const args = process.argv.slice(2)
const mode = args[0]
const opt = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback }
const runs = fs.readdirSync(path.join(here, "results")).filter((d) => d.startsWith("LT-") && fs.existsSync(path.join(here, "results", d, "run.json"))).sort()
const runId = opt("--run", process.env.LT_RUN || runs[runs.length - 1])
const run = JSON.parse(fs.readFileSync(path.join(here, "results", runId, "run.json"), "utf8"))
const host = (opt("--host", process.env.LT_HOST || run.host)).replace(/\/$/, "")
const outDir = path.join(here, "results", runId, "screens")
fs.mkdirSync(outDir, { recursive: true })
const insecure = process.env.LT_INSECURE === "1"
const shot = (page, name) => page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: false })
const ms = async (fn) => { const t = Date.now(); await fn(); return Date.now() - t }

async function candidate(browser, who, index, timings) {
  const ctx = await browser.newContext({ baseURL: host, ignoreHTTPSErrors: insecure, viewport: { width: 1280, height: 800 } })
  const page = await ctx.newPage()
  const t = {}
  try {
    await page.goto("/login")
    await page.getByLabel("Username or email").fill(who.username)
    await page.getByLabel("Password", { exact: true }).fill(who.password)
    t.sign_in = await ms(async () => { await page.getByRole("button", { name: "Sign in" }).click(); await page.getByRole("heading", { name: "Your exams" }).waitFor({ timeout: 60000 }) })
    await page.locator("div[data-slot=card]").filter({ hasText: run.browser_exam.title }).getByRole("link", { name: /Start|Resume/ }).click()
    await page.getByLabel(/I understand and agree/).click()
    t.start = await ms(async () => { await page.getByRole("button", { name: "Start exam" }).click(); await page.getByTestId("timer").waitFor({ timeout: 60000 }) })
    if (index === 0) await shot(page, "real-browser-candidate-exam-under-load")
    const turns = []
    for (let i = 0; i < 5; i++) {
      await page.getByText(/Option [A-D] of/).first().click()
      const next = page.getByRole("button", { name: /^(Save and next|Next section|Finish)/ })
      turns.push(await ms(async () => { await next.click(); await page.waitForTimeout(150) }))
      await page.waitForTimeout(1500 + Math.random() * 1500)
    }
    t.next_question_ms = Math.round(turns.reduce((a, b) => a + b, 0) / turns.length)
    t.answered_ok = true
  } catch (e) {
    t.error = String(e).slice(0, 160)
    await shot(page, `real-browser-candidate-${index}-problem`).catch(() => {})
  }
  timings.push(t)
  await ctx.close()
}

async function staff(browser) {
  const ctx = await browser.newContext({ baseURL: host, ignoreHTTPSErrors: insecure, viewport: { width: 1360, height: 900 } })
  const page = await ctx.newPage()
  const t = {}
  await page.goto("/login")
  await page.getByLabel("Username or email").fill(run.staff_email)
  await page.getByLabel("Password", { exact: true }).fill(run.staff_password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.waitForURL(/\/admin/, { timeout: 60000 })
  const pages = [["staff-question-bank", `/admin/questions`, "Question bank"], ["staff-users", `/admin/users`, "Users"], ["staff-live-monitor", `/admin/monitor?exam=${run.exam_id}`, "Live monitor"],
                 ["staff-results-test-exam", `/admin/results/${run.exam_id}`, "Pass mark"]]
  if (run.big_exam_id) pages.push(["staff-results-big-exam", `/admin/results/${run.big_exam_id}`, "Pass mark"], ["staff-analytics-big-exam", `/admin/results/${run.big_exam_id}?tab=analytics`, "Analytics"])
  for (const [name, url, ready] of pages) {
    t[name] = await ms(async () => { await page.goto(url); await page.getByText(ready, { exact: false }).first().waitFor({ timeout: 120000 }); await page.waitForTimeout(1500) })
    await shot(page, name)
  }
  await ctx.close()
  return t
}

const browser = await chromium.launch()
const out = { at: new Date().toISOString(), host, mode }
if (mode === "candidates") {
  const people = run.browser_exam.candidates
  const timings = []
  await Promise.all(people.map((who, i) => candidate(browser, who, i, timings)))
  out.timings = timings
  const ok = timings.filter((t) => t.answered_ok)
  const avg = (k) => Math.round(ok.reduce((a, t) => a + (t[k] || 0), 0) / Math.max(ok.length, 1))
  out.summary = { browsers: people.length, worked: ok.length, sign_in_ms: avg("sign_in"), start_exam_ms: avg("start"), next_question_ms: avg("next_question_ms") }
} else {
  out.timings = await staff(browser)
}
await browser.close()
fs.writeFileSync(path.join(here, "results", runId, `browsers-${mode}.json`), JSON.stringify(out, null, 2))
console.log(JSON.stringify(out.summary || out.timings))
