import { expect, test } from "@playwright/test"
import { login, newParticipant, shot, startProctoredExam } from "./helpers"

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
