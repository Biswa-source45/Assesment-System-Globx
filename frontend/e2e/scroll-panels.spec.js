import { expect, test } from "@playwright/test"
import { login, newParticipant, shot, staffRequest, startProctoredExam } from "./helpers"

// On a laptop screen the page itself never scrolls: the title bar, the camera and the buttons stay, and the parts with long text scroll on their own.

const noPageScroll = (page) => page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1)

test("check-in: the page stays put, the rules scroll on their own, Start and the camera stay in view", async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 600 })
  const p = await newParticipant(request, "Scroll Checkin")
  await login(page, p.username, p.password)
  await page.locator("div[data-slot=card]").filter({ hasText: "GLOBX Full-Stack Screening (Sample)" }).getByRole("link", { name: /Start|Resume/ }).click()
  await expect(page.getByTestId("rules-scroll")).toBeVisible()
  expect(await noPageScroll(page)).toBe(true)
  const rules = page.getByTestId("rules-scroll")
  expect(await rules.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)        // the rules are longer than the box: they scroll inside it
  await expect(page.getByText("GLOBX Full-Stack Screening (Sample)", { exact: true })).toBeInViewport()    // the exam title
  await expect(page.getByRole("button", { name: /start exam/i })).toBeInViewport()          // the Start button is never scrolled away
  await expect(page.getByRole("button", { name: "Enable camera" })).toBeInViewport()
  await rules.evaluate((el) => { el.scrollTop = el.scrollHeight })
  expect(await rules.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  await expect(page.getByText("GLOBX Full-Stack Screening (Sample)", { exact: true })).toBeInViewport()    // still there after scrolling the rules
  await shot(page, "checkin-scroll")
})

test("exam: the question and the code each scroll on their own, the page does not", async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 640 })
  const p = await newParticipant(request, "Scroll Exam")
  await startProctoredExam(page, p.username, "GLOBX Full-Stack Screening (Sample)", p.password)
  // walk the sections and questions until the coding question (the one with an editor) shows
  const sections = page.locator("button", { hasText: /·\s*\d+\/\d+/ })
  let found = false
  for (let s = 0; s < (await sections.count()) && !found; s++) {
    await sections.nth(s).click()
    const palette = page.getByLabel("Question palette").getByRole("button")
    for (let i = 0; i < (await palette.count()) && !found; i++) {
      await palette.nth(i).click()
      found = (await page.locator(".cm-content").count()) > 0
    }
  }
  expect(found).toBe(true)
  await shot(page, "exam-scroll-panels")
  const q = page.getByTestId("question-panel"), c = page.getByTestId("code-panel")
  expect(await noPageScroll(page)).toBe(true)
  await expect(page.getByTestId("timer")).toBeInViewport()                                  // the top bar
  await expect(page.getByRole("button", { name: "Previous" })).toBeInViewport()             // the buttons under the work
  const box = (el) => el.evaluate((e) => ({ scroll: e.scrollHeight > e.clientHeight, top: e.scrollTop }))
  expect((await box(c)).scroll).toBe(true)                                                  // the editor and its results are longer than the screen: they scroll
  await c.evaluate((e) => { e.scrollTop = 150 })
  expect((await box(c)).top).toBeGreaterThan(0)
  expect((await box(q)).top).toBe(0)                                                        // scrolling the code does not move the question
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
  await q.evaluate((e) => { e.scrollTop = e.scrollHeight })
  expect((await box(c)).top).toBeGreaterThan(0)                                             // and the other way round
  await expect(page.getByTestId("timer")).toBeInViewport()
})

// The camera sits in the top bar, the sections are one row that scrolls sideways, and wide text can never stretch a panel past the screen.
test("exam: camera in the top bar, one row of sections, wide text scrolls inside its own box", async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 700 })
  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const title = "E2E Wide Layout Exam"
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, shuffle_questions: false, shuffle_options: false,
    settings: { proctoring: { enabled: true, webcam: true, fullscreen: false, block_multi_display: false } } })
  const wide = '{"username":"asha","email":"asha@example.com","password":"secret123","extra":"' + "x".repeat(260) + '"}'
  for (const n of [1, 2, 3, 4, 5, 6]) {
    const section = (await api.post(`/tests/${exam.id}/sections`, { title: `Section ${n}: A long section name for the layout check` })).sections[n - 1]
    const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `Wide ${n}`, marks: 1,
      body: `<p>Question ${n}. ${"A long sentence that has to wrap inside the panel. ".repeat(8)}</p><pre>${wide}</pre>`,
      config: { options: [{ id: "a", text: "Yes", correct: true }, { id: "b", text: "No", correct: false }] } })
    await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  }
  await api.post(`/tests/${exam.id}/publish`)
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: ["Wide Layout"] })).participants[0]
  await page.addInitScript(() => { window.__faceCount = 1 })
  await login(page, p.username, p.password)
  await page.locator("div[data-slot=card]").filter({ hasText: title }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Enable camera" }).click()
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected", { timeout: 15_000 })
  await page.getByLabel(/I understand and agree/).click()
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)

  const cam = page.locator("header").getByTestId("camera-box")                                // the camera is in the top bar
  await expect(cam).toContainText("Face OK")
  expect((await cam.boundingBox()).height).toBeLessThan(80)
  const row = page.getByLabel("Sections", { exact: true })                                    // six long names: still one row, scrolling sideways
  expect((await row.boundingBox()).height).toBeLessThan(60)
  expect(await row.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  const q = page.getByTestId("question-panel")
  expect((await q.boundingBox()).height).toBeGreaterThan(300)                                 // the room the camera and three rows of tabs used to take
  expect(await q.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)           // the text wraps inside the panel
  const pre = q.locator("pre")
  expect(await pre.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)              // the wide line scrolls inside its own box
  await pre.evaluate((el) => { el.scrollLeft = 200 })
  expect(await pre.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
  await shot(page, "exam-wide-layout")

  const last = page.getByRole("button", { name: /^Section 6/ })                                // going to the last section brings its tab into view
  await last.click()
  await expect(last).toBeInViewport()
  await expect(page.getByTestId("timer")).toBeInViewport()
})

// Instructions are pasted as formatted text (headings, bullets, bold) and the candidate sees them formatted, not as one run-on paragraph.
test("check-in: formatted exam instructions show as headings, bullets and bold", async ({ page, request }) => {
  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const title = "E2E Instructions Exam"
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { enabled: false } },
    instructions: "<h4>ABOUT THE TEST</h4><p>Total time: <b>120 minutes</b>. The timer cannot be paused.</p><h4>MARKING</h4><ul><li>Single answer: 1 mark.</li><li>A wrong answer loses 0.5 marks.</li></ul>" })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: "Instr Q", body: "<p>x</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: ["Instr Reader"] })).participants[0]
  await login(page, p.username, p.password)
  await page.locator("div[data-slot=card]").filter({ hasText: title }).getByRole("link", { name: /Start|Resume/ }).click()
  const box = page.getByTestId("exam-instructions")
  await expect(box.locator("h4")).toHaveText(["ABOUT THE TEST", "MARKING"])
  expect(Number(await box.locator("h4").first().evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(600)
  expect(await box.locator("li").first().evaluate((el) => getComputedStyle(el).listStyleType)).toBe("disc")      // real bullets
  await expect(box.locator("b")).toHaveText("120 minutes")
  await shot(page, "checkin-instructions")
})
