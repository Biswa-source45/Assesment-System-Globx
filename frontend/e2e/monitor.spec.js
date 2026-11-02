import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, newParticipant, shot, staffRequest, startProctoredExam } from "./helpers"

const SAMPLE = "GLOBX Full-Stack Screening (Sample)"
const setFaces = (page, n) => page.evaluate((v) => { window.__faceCount = v }, n)

async function monitorRow(page, request, name) {
  const api = await staffRequest(request)
  const exam = (await api.get("/tests")).find((t) => t.title === SAMPLE)
  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${exam.id}`)
  return page.getByTestId("monitor-row").filter({ hasText: name })
}

async function chooseAction(page, row, name, menuItem) {
  await row.getByRole("button", { name: `Actions for ${name}` }).click()
  await page.getByRole("menuitem", { name: menuItem }).click()
}

test("the live monitor follows a candidate; the admin extends the time, then ends the exam", async ({ page, browser, request }) => {
  const p = await newParticipant(request, "Monitor Target")
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, p.username, SAMPLE, p.password)

  const row = await monitorRow(page, request, "Monitor Target")
  await expect(row.getByTestId("monitor-status")).toHaveText("In progress")
  await expect(row.getByTestId("time-left")).toContainText(/^1:2\d:/)  // a 90 minute exam that has only just started
  await expect(row.getByTestId("monitor-leaves")).toHaveText("0 / 3")
  await expect(row.getByTestId("monitor-faces")).toHaveText("0 / 5")
  await expect(row.getByAltText("Latest camera snapshot")).toBeVisible({ timeout: 30_000 })  // the camera picture, fetched with the login header
  await shot(page, "monitor-live")

  // what the candidate does shows up within a poll
  await cand.evaluate(async () => {
    window.dispatchEvent(new Event("blur"))
    await new Promise((r) => setTimeout(r, 1300))
    window.dispatchEvent(new Event("focus"))
  })
  await expect(row.getByTestId("monitor-leaves")).toHaveText("1 / 3", { timeout: 15_000 })
  await setFaces(cand, 0)
  await expect(row.getByTestId("monitor-faces")).toHaveText("1 / 5", { timeout: 20_000 })
  await setFaces(cand, 1)
  await expect(page.getByTestId("monitor-summary")).toContainText(/[1-9]\d* in progress/)  // others may be mid-exam too: this test only needs a non-zero count
  await shot(page, "monitor-warnings")

  // extending the time reaches the candidate's timer through the clock check
  await expect(cand.getByTestId("timer")).toContainText(/^1:2\d:/)  // still the original 90 minutes
  await chooseAction(page, row, "Monitor Target", "Extend time")
  await page.getByLabel("Minutes to add").fill("15")
  await page.getByLabel("Reason").fill("slow laptop")
  await page.getByRole("button", { name: "Extend", exact: true }).click()
  await expect(cand.getByTestId("timer")).toHaveText(/^1:4\d:\d\d$/, { timeout: 30_000 })  // 90 + 15 minutes, a little used

  // ending the exam: the candidate's screen leaves the exam on its own
  await chooseAction(page, row, "Monitor Target", "End exam now")
  await page.getByLabel("Reason").fill("fire drill")
  await page.getByRole("button", { name: "End exam", exact: true }).click()
  await expect(cand).toHaveURL(/\/exam\/done\/.*why=ended/, { timeout: 30_000 })
  await expect(cand.getByTestId("done-title")).toHaveText("Exam ended")
  await expect(row.getByTestId("monitor-status")).toHaveText(/Submitted|Marked/, { timeout: 15_000 })  // graded straight away when nothing needs a person
  await expect(row).toContainText("Ended by admin")

  // the same participant can be let back in
  await chooseAction(page, row, "Monitor Target", "Re-open exam")
  await page.getByLabel("Reason").fill("laptop problem, not their fault")
  await page.getByRole("button", { name: "Re-open", exact: true }).click()
  await expect(row.getByTestId("monitor-status")).toHaveText("Not started", { timeout: 15_000 })
  await ctx.close()
})

test("the monitor shows a locked candidate and the admin can re-open the exam", async ({ page, browser, request }) => {
  const p = await newParticipant(request, "Locked Out")
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, p.username, SAMPLE, p.password)
  const row = await monitorRow(page, request, "Locked Out")
  await expect(row.getByTestId("monitor-status")).toHaveText("In progress")

  for (const n of [1, 2, 3, 4, 5]) {  // five face problems end the exam and lock the login
    await setFaces(cand, n % 2 ? 0 : 2)
    await expect(row.getByTestId("monitor-faces")).toHaveText(`${n} / 5`, { timeout: 20_000 })
    await setFaces(cand, 1)
    if (n < 5) await expect(cand.getByTestId("camera-box")).toContainText("Face OK")  // the problem must visibly end before the next one starts
  }
  await expect(row.getByTestId("monitor-status")).toHaveText("Locked", { timeout: 15_000 })
  await expect(row).toContainText("Face rule: locked")
  await expect(page.getByTestId("monitor-summary")).toContainText(/[1-9]\d* locked/)
  await shot(page, "monitor-locked")

  await chooseAction(page, row, "Locked Out", "Re-open exam")
  await page.getByLabel("Reason").fill("camera was covered by a reflection")
  await page.getByRole("button", { name: "Re-open", exact: true }).click()
  await expect(row.getByTestId("monitor-status")).toHaveText("Not started", { timeout: 15_000 })
  await ctx.close()
})

test("a new password for a participant is shown once and works", async ({ page, request }) => {
  const p = await newParticipant(request, "Forgot Password")
  const row = await monitorRow(page, request, "Forgot Password")
  await chooseAction(page, row, "Forgot Password", "New password")
  const shown = (await page.getByTestId("new-password").innerText()).replace("Password: ", "")
  expect(shown).not.toBe(p.password)
  const login = await request.post("/api/v1/auth/login", { data: { email: p.username, password: shown } })
  expect(login.ok()).toBeTruthy()
  const old = await request.post("/api/v1/auth/login", { data: { email: p.username, password: p.password } })
  expect(old.status()).toBe(401)
})
