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

test("a tile that is not live is connected again by hand with Reconnect, and Reconnect all does the same for every such tile", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const t = await liveExam(api, "E2E Live Reconnect Exam")
  const p = (await api.post(`/tests/${t.id}/participants`, { names: ["Redial Candidate"] })).participants[0]
  const net = { drop: true, asked: 0, offers: 0 }      // while `drop` is on, neither browser gets its connection details through: the network "blocks" video
  const gate = (pg, examiner) => pg.routeWebSocket(/\/api\/v1\/live\//, (ws) => {
    const server = ws.connectToServer()
    ws.onMessage((m) => { const type = JSON.parse(String(m)).type; if (type === "reconnect") net.asked++; if (!(net.drop && type === "ice")) server.send(m) })
    server.onMessage((m) => { if (examiner && JSON.parse(String(m)).type === "offer") net.offers++; ws.send(m) })
  })
  const cand = await candidateWindow(browser)
  await gate(cand.page, false)
  await startProctoredExam(cand.page, p.username, "E2E Live Reconnect Exam", p.password)
  await gate(page, true)
  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${t.id}`)
  await page.getByRole("button", { name: "Live view" }).click()
  const card = page.getByTestId("live-card").filter({ hasText: "Redial Candidate" })
  await expect(card.getByTestId("live-state")).toHaveText("Cannot connect", { timeout: 40_000 })
  await expect(page.getByText("1 of 1 not live.")).toBeVisible()

  // the network is fine again; the examiner asks for the connection by hand
  net.drop = false
  const offersBefore = net.offers
  await card.getByRole("button", { name: "Reconnect Redial Candidate" }).click()
  await expect(card.getByTestId("live-state")).toHaveText("Connecting")                         // at once: the old line is dropped
  await expect.poll(() => net.asked, { message: "the examiner's browser must ask the server to reconnect" }).toBe(1)
  await expect.poll(() => net.offers, { message: "the candidate's browser must offer again" }).toBeGreaterThan(offersBefore)
  await expect(card.getByTestId("live-state")).toHaveText("Live", { timeout: 30_000 })
  await expect.poll(() => card.getByLabel("Redial Candidate camera").evaluate((v) => v.readyState >= 2 && v.videoWidth > 0), { timeout: 30_000 }).toBe(true)
  await expect(card.getByRole("button", { name: "Reconnect Redial Candidate" })).toHaveCount(0)   // nothing to fix any more
  await expect(page.getByTestId("reconnect-all")).toHaveCount(0)
  await shot(page, "live-reconnected")

  // a candidate who left the room: the button says so instead of doing nothing
  await cand.ctx.close()
  await expect(page.getByTestId("live-card").filter({ hasText: "Redial Candidate" }).getByTestId("live-state")).toHaveText("Not connected", { timeout: 20_000 })
  await page.getByTestId("live-card").filter({ hasText: "Redial Candidate" }).getByRole("button", { name: "Reconnect Redial Candidate" }).click()
  await expect(page.getByText("browser is not in the live room right now")).toBeVisible()
})
