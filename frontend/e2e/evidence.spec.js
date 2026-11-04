import fs from "node:fs"
import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest, startProctoredExam } from "./helpers"

const dialog = (page) => page.getByRole("dialog")
const attemptOf = (page) => page.url().split("/").pop()

async function exam(api, title, proctoring) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>Pick A.</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring } })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${t.id}/publish`)
  return t
}

async function person(api, examId, name) {
  return (await api.post(`/tests/${examId}/participants`, { names: [name] })).participants[0]
}

const events = async (api, at) => (await api.get(`/reports/attempts/${at}`)).proctoring.counts

test("pictures mode: the screen is shared, a picture of it is kept during the exam, and the review shows it", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await exam(api, "E2E Screen Pictures Exam", { screen_share: true, evidence: "pictures", screenshot_seconds: 10, snapshot_seconds: 5 })
  const p = await person(api, t.id, "Pic Screen")
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, p.username, "E2E Screen Pictures Exam", p.password)
  const at = attemptOf(cand)

  await expect.poll(async () => (await api.get(`/reports/attempts/${at}`)).proctoring.snapshots.filter((s) => s.kind === "screen").length, { timeout: 45_000 }).toBeGreaterThanOrEqual(2)
  await cand.getByRole("button", { name: "End exam" }).click()
  await dialog(cand).getByRole("button", { name: /^(Submit|End exam|Yes)/ }).first().click()
  await expect(cand).toHaveURL(/\/exam\/done\//)
  await ctx.close()

  await loginStaff(page)
  await page.goto(`/admin/results/${t.id}/${at}`)
  await expect(page.getByTestId("screen-pictures").locator("figure")).not.toHaveCount(0)
  await expect(page.getByTestId("recordings")).toHaveCount(0)  // this exam keeps pictures, not video
  await shot(page, "evidence-screen-pictures")

  // A picture opens full size in a dialog, with Previous/Next and the arrow keys; Escape closes it.
  const thumb = page.getByTestId("screen-pictures").locator("img").first()
  await expect.poll(() => thumb.evaluate((i) => i.naturalWidth)).toBeGreaterThan(0)
  const small = (await thumb.boundingBox()).width
  await page.getByTestId("screen-pictures").getByRole("button", { name: /Open the screen picture/ }).first().click()
  const viewer = page.getByTestId("picture-viewer")
  const big = viewer.getByRole("img", { name: /Full size screen picture/ })
  await expect(viewer).toContainText("Picture 1 of")
  await expect.poll(() => big.evaluate((i) => i.naturalWidth)).toBeGreaterThan(0)
  expect((await big.boundingBox()).width).toBeGreaterThan(small * 3)
  await shot(page, "evidence-picture-viewer")
  await viewer.getByRole("button", { name: "Next" }).click()
  await expect(viewer).toContainText("Picture 2 of")
  await page.keyboard.press("ArrowLeft")
  await expect(viewer).toContainText("Picture 1 of")
  await page.keyboard.press("Escape")
  await expect(viewer).toHaveCount(0)
})

test("video mode: the whole exam is recorded in pieces, kept for review with a deletion date, and playable", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await exam(api, "E2E Video Exam", { screen_share: true, evidence: "video", video_retention_days: 14 })
  const p = await person(api, t.id, "Vid Eo")
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, p.username, "E2E Video Exam", p.password)
  const at = attemptOf(cand)
  await cand.waitForTimeout(13_000)  // a piece is 10 seconds
  await cand.getByRole("button", { name: "End exam" }).click()
  await dialog(cand).getByRole("button", { name: /^(Submit|End exam|Yes)/ }).first().click()  // the last piece is sent before the exam ends
  await expect(cand).toHaveURL(/\/exam\/done\//)
  await ctx.close()

  const list = async () => (await api.get(`/attempts/${at}/recordings`))
  await expect.poll(async () => (await list()).recordings.filter((r) => r.bytes > 0).map((r) => r.kind).sort(), { timeout: 20_000 }).toEqual(["screen", "webcam"])
  expect((await list()).retention_days).toBe(14)
  expect((await api.get(`/reports/attempts/${at}`)).proctoring.snapshots.filter((s) => s.kind === "screen")).toHaveLength(0)  // video replaces the screen pictures

  await loginStaff(page)
  await page.goto(`/admin/results/${t.id}/${at}`)
  await expect(page.getByTestId("recording")).toHaveCount(2)
  await expect(page.getByTestId("recording").first()).toContainText("Deleted on")
  const camera = page.getByTestId("recording").filter({ hasText: "Camera video" })
  await camera.getByRole("button", { name: "Play" }).click()
  const player = page.getByTestId("recording-player")
  await expect(player).toBeVisible()
  await expect.poll(() => player.evaluate((v) => v.readyState), { timeout: 15_000 }).toBeGreaterThanOrEqual(2)  // the browser can decode it
  expect(await player.evaluate((v) => v.videoWidth)).toBeGreaterThan(0)
  const download = page.waitForEvent("download")
  await camera.getByRole("button", { name: "Download" }).click()
  expect(fs.statSync(await (await download).path()).size).toBeGreaterThan(1000)
  await shot(page, "evidence-video-review")
})

test("live view: the examiner sees every camera and screen, talks to one candidate only, sends a message, and a stopped share is caught", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await exam(api, "E2E Live Exam", { screen_share: true, live_view: true, evidence: "pictures" })
  const [ana, ben] = [await person(api, t.id, "Ana Live"), await person(api, t.id, "Ben Live")]
  const a = await candidateWindow(browser)
  const b = await candidateWindow(browser)
  await startProctoredExam(a.page, ana.username, "E2E Live Exam", ana.password)
  await startProctoredExam(b.page, ben.username, "E2E Live Exam", ben.password)

  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${t.id}`)
  await page.getByRole("button", { name: "Live view" }).click()
  const card = (name) => page.getByTestId("live-card").filter({ hasText: name })
  await expect(page.getByTestId("live-card")).toHaveCount(2)
  for (const name of ["Ana Live", "Ben Live"]) {
    await expect(card(name).getByTestId("live-state")).toHaveText("Live", { timeout: 30_000 })
    await expect(card(name).locator("video[data-live=yes]")).toHaveCount(2)  // camera and screen
  }
  await expect.poll(() => card("Ana Live").getByLabel("Ana Live screen").evaluate((v) => v.readyState >= 2 && v.videoWidth > 0), { timeout: 20_000 }).toBe(true)  // moving picture, not an empty tile
  await shot(page, "live-grid")

  // a private line to Ana: Ben hears and sees nothing; the other invigilator would find it busy
  await card("Ana Live").getByRole("button", { name: "Talk" }).click()
  await expect(a.page.getByTestId("talk-banner")).toBeVisible({ timeout: 10_000 })
  await expect(b.page.getByTestId("talk-banner")).toHaveCount(0)
  await expect(card("Ana Live").getByRole("button", { name: "End talk" })).toBeVisible()
  await expect(card("Ben Live").getByRole("button", { name: "Talk" })).toBeEnabled()
  await card("Ana Live").getByRole("button", { name: "End talk" }).click()
  await expect(a.page.getByTestId("talk-banner")).toHaveCount(0)

  // a message reaches only Ben
  await card("Ben Live").getByRole("button", { name: "Message" }).click()
  await dialog(page).getByLabel("Message").fill("Please keep your eyes on your own screen.")
  await dialog(page).getByRole("button", { name: "Send" }).click()
  await expect(b.page.getByTestId("invigilator-message")).toHaveText("Please keep your eyes on your own screen.")
  await expect(a.page.getByTestId("invigilator-message")).toHaveCount(0)
  await b.page.getByRole("button", { name: "OK" }).click()

  // the talk and the message are in the candidates' timelines
  const [atA, atB] = [attemptOf(a.page), attemptOf(b.page)]
  await expect.poll(async () => (await events(api, atA)).talk_started, { timeout: 10_000 }).toBe(1)
  expect((await events(api, atA)).talk_ended).toBe(1)
  await expect.poll(async () => (await events(api, atB)).message_sent, { timeout: 10_000 }).toBe(1)

  // Ben presses "Stop sharing": it is a warning, the exam asks for the screen again, and the live tile comes back after sharing
  await b.page.evaluate(() => { const t = window.__media.screen.getVideoTracks()[0]; t.stop(); t.dispatchEvent(new Event("ended")) })
  await expect(dialog(b.page)).toContainText("Warning 1 of 3: leaving fullscreen, switching tabs or stopping the screen share is recorded.")
  await b.page.getByRole("button", { name: "I understand, continue" }).click()
  await expect(b.page.getByRole("heading", { name: "Share your screen to continue" })).toBeVisible()  // after the warning, the exam waits until the screen is shared again
  await expect.poll(async () => (await events(api, atB)).screen_share_stopped, { timeout: 10_000 }).toBe(1)
  await expect(b.page.getByTestId("violations")).toHaveText("Warnings 1 / 3")
  await b.page.getByRole("button", { name: "Share my screen" }).click()
  await expect(b.page.getByRole("heading", { name: "Share your screen to continue" })).toHaveCount(0)
  await expect(card("Ben Live").getByTestId("live-state")).toHaveText("Live", { timeout: 30_000 })
  await expect(card("Ben Live").locator("video[data-live=yes]")).toHaveCount(2, { timeout: 30_000 })
  await a.ctx.close()
  await b.ctx.close()
})

test("the exam's evidence settings are chosen in the exam details", async ({ page, request }) => {
  const api = await staffRequest(request)
  const t = await exam(api, "E2E Evidence Settings Exam", {})
  await api.post(`/tests/${t.id}/unpublish`)
  await loginStaff(page)
  await page.goto(`/admin/exams/${t.id}`)
  await expect(page.getByLabel("Evidence kept")).toContainText("Pictures")
  await page.getByLabel("Candidate shares their entire screen").click()
  await page.getByLabel("Live view for the invigilator").click()
  await page.getByLabel("Evidence kept").click()
  await page.getByRole("option", { name: /^Video of the whole exam/ }).click()
  await page.getByLabel("Delete the video after (days)").fill("7")
  await page.getByRole("button", { name: "Save exam" }).click()
  await expect(page.getByText("Exam saved")).toBeVisible()
  const saved = (await api.get(`/tests/${t.id}`)).settings.proctoring
  expect([saved.evidence, saved.screen_share, saved.live_view, saved.video_retention_days]).toEqual(["video", true, true, 7])
  await shot(page, "evidence-settings")
})
