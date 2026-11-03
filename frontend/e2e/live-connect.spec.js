import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest, startProctoredExam } from "./helpers"

// The real office network showed black tiles. Two things were true there and are made true here:
//  - the examiner's browser is slow to get its connection settings (/live/ice), so the candidate's first connection details arrive before it is ready;
//  - one side cannot reach the other's address (the examiner's page hides its address behind a ".local" name), so only the details the candidate sends
//    can make the connection. Dropped details = a tile that says Live and shows nothing.
const frames = (card, label) => card.getByLabel(label).evaluate((v) => v.readyState >= 2 && v.videoWidth > 0)

async function liveExam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>Pick A.</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { screen_share: true, live_view: true, evidence: "pictures" } } })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${t.id}/publish`)
  return t
}

// Drops the connection details ("ice" messages) that this page's WebSocket sends to the server.
const dropOutgoingDetails = (page) => page.routeWebSocket(/\/api\/v1\/live\//, (ws) => {
  const server = ws.connectToServer()
  ws.onMessage((m) => { if (JSON.parse(String(m)).type !== "ice") server.send(m) })
  server.onMessage((m) => ws.send(m))
})

test("the live view shows moving pictures when the examiner's settings are slow and only the candidate's connection details get through", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await liveExam(api, "E2E Live Race Exam")
  const p = (await api.post(`/tests/${t.id}/participants`, { names: ["Race Candidate"] })).participants[0]
  const cand = await candidateWindow(browser)
  await startProctoredExam(cand.page, p.username, "E2E Live Race Exam", p.password)

  await page.route("**/api/v1/live/ice", async (route) => { await new Promise((r) => setTimeout(r, 700)); await route.continue() })
  await dropOutgoingDetails(page)
  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${t.id}`)
  await page.getByRole("button", { name: "Live view" }).click()
  const card = page.getByTestId("live-card").filter({ hasText: "Race Candidate" })
  await expect(card).toBeVisible()
  await expect.poll(() => frames(card, "Race Candidate camera"), { timeout: 30_000, message: "the camera tile must show moving pictures, not stay black" }).toBe(true)
  await expect.poll(() => frames(card, "Race Candidate screen"), { timeout: 30_000, message: "the screen tile must show moving pictures, not stay black" }).toBe(true)
  await shot(page, "live-race-connected")
  await cand.ctx.close()
})

test("when the network lets no video through, the tile says so instead of staying black", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await liveExam(api, "E2E Live Blocked Exam")
  const p = (await api.post(`/tests/${t.id}/participants`, { names: ["Blocked Candidate"] })).participants[0]
  const cand = await candidateWindow(browser)
  await dropOutgoingDetails(cand.page)  // neither side can tell the other where to send video
  await startProctoredExam(cand.page, p.username, "E2E Live Blocked Exam", p.password)

  await dropOutgoingDetails(page)
  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${t.id}`)
  await page.getByRole("button", { name: "Live view" }).click()
  const card = page.getByTestId("live-card").filter({ hasText: "Blocked Candidate" })
  await expect(card.getByTestId("live-state")).toHaveText("Connecting", { timeout: 15_000 })
  await expect(card.getByTestId("live-note").first()).toHaveText("Connecting...")
  await expect(card.getByTestId("live-state")).toHaveText("Cannot connect", { timeout: 40_000 })  // after 15 s without a connection
  await expect(card.getByTestId("live-note").first()).toContainText("Cannot connect: the network does not let these two computers send video")
  await expect(card.getByTestId("live-state")).not.toHaveText("Live")
  await shot(page, "live-cannot-connect")
  await cand.ctx.close()
})
