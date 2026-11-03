import { expect, test } from "@playwright/test"
import { candidateWindow, login, shot, staffRequest } from "./helpers"

// The candidate does not hunt for a screen-share option: one "Accept and start exam" press asks Chrome to share (Entire screen preselected)
// and enters full screen. Chrome's own box cannot be skipped by a website; in the tests the browser answers it by itself.
async function shared(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>Pick A.</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { screen_share: true, evidence: "pictures" } } })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${t.id}/publish`)
  return (await api.post(`/tests/${t.id}/participants`, { names: ["Screen Starter"] })).participants[0]
}

test("one 'Accept and start exam' press shares the entire screen and enters full screen; a window or tab is refused", async ({ browser, request }) => {
  const api = await staffRequest(request)
  const p = await shared(api, "E2E Screen Start Exam")
  const { ctx, page } = await candidateWindow(browser)
  await login(page, p.username, p.password)
  await page.addInitScript(() => { window.__faceCount = 1 })
  await page.evaluate(() => { window.__faceCount = 1 })
  await page.locator("div[data-slot=card]").filter({ hasText: "E2E Screen Start Exam" }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Enable camera" }).click()
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected", { timeout: 15_000 })

  // nothing about sharing to find or press: no card, no button, no badge; the rules say what will happen
  await expect(page.getByRole("button", { name: "Share my screen" })).toHaveCount(0)
  await expect(page.getByText("Screen share", { exact: true })).toHaveCount(0)
  await expect(page.getByText("Your browser asks you once, when you press the start button")).toBeVisible()
  const start = page.getByRole("button", { name: "Accept and start exam" })
  await expect(start).toBeDisabled()                                   // until the person has agreed
  await page.getByLabel(/I understand and agree/).click()
  await expect(start).toBeEnabled()
  await shot(page, "screen-start-checkin")

  // the person picks a window: refused, back out of full screen, nothing started
  await page.evaluate(() => { window.__displaySurface = "window" })
  await start.click()
  await expect(page.getByText("Please share your entire screen, not a window or a tab.")).toBeVisible()
  await expect(page).toHaveURL(/\/start$/)
  expect(await page.evaluate(() => !!document.fullscreenElement)).toBe(false)
  expect(await page.evaluate(() => !!window.__media.screen)).toBe(false)

  // then the whole screen: one press, the exam is running, the screen is shared and the page is in full screen
  await page.evaluate(() => { window.__displaySurface = undefined })
  await start.click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)
  await expect(page.getByText("Proctoring on")).toBeVisible()
  expect(await page.evaluate(() => window.__media.screen.getVideoTracks()[0].readyState)).toBe("live")
  expect(await page.evaluate(() => !!document.fullscreenElement)).toBe(true)
  await expect(page.getByRole("heading", { name: "Share your screen to continue" })).toHaveCount(0)
  await expect(page.getByRole("heading", { name: /full screen/i })).toHaveCount(0)   // no "return to full screen" detour
  await shot(page, "screen-start-exam")
  await ctx.close()
})
