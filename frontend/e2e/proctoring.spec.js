import { expect, test } from "@playwright/test"
import { loginCandidate, shot, startProctoredExam } from "./helpers"

const setFaces = (page, n) => page.evaluate((v) => { window.__faceCount = v }, n)
const leaveTabFor = (page, ms) => page.evaluate(async (t) => {
  window.dispatchEvent(new Event("blur"))
  await new Promise((r) => setTimeout(r, t))
  window.dispatchEvent(new Event("focus"))
}, ms)

test("face gate: Start stays locked with no face, opens with one face and consent", async ({ page }) => {
  await loginCandidate(page, "rahul")
  await page.locator("div[data-slot=card]").filter({ hasText: "GLOBX Full-Stack Screening" }).getByRole("link", { name: "Start" }).click()
  await expect(page.getByText("3 times")).toBeVisible()      // the tab rule is shown in plain words
  await expect(page.getByText("5 face warnings")).toBeVisible()
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await page.getByRole("button", { name: "Enable camera" }).click()
  // the real MediaPipe pipeline (wasm + model) must load and give a verdict on the fake camera picture
  await expect(page.getByTestId("face-status")).not.toHaveText("Waiting for camera", { timeout: 20_000 })
  await setFaces(page, 0)  // then pin the count, because the fake picture is not a real face
  await expect(page.getByTestId("face-status")).toHaveText("No face detected")
  await page.getByLabel(/I understand and agree/).click()
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await shot(page, "checkin-no-face")
  await setFaces(page, 2)
  await expect(page.getByTestId("face-status")).toHaveText("2 faces detected")
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await setFaces(page, 1)
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected")
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
  await shot(page, "checkin-ready")
})

test("4th tab leave ends the exam after three warnings", async ({ page }) => {
  await startProctoredExam(page, "rahul")
  await expect(page.getByTestId("violations")).toHaveText("Warnings 0 / 3")
  await shot(page, "exam-proctored")
  for (const n of [1, 2, 3]) {
    await leaveTabFor(page, 1300)
    await expect(page.getByText(`Warning ${n} of 3`)).toBeVisible({ timeout: 10_000 })
    if (n === 1) await shot(page, "exam-warning")
    await page.getByRole("button", { name: "I understand, continue" }).click()
    await expect(page.getByTestId("violations")).toHaveText(`Warnings ${n} / 3`)
  }
  await leaveTabFor(page, 1300)
  await expect(page).toHaveURL(/\/exam\/done\/.*why=force_submit/, { timeout: 10_000 })
  await expect(page.getByTestId("done-title")).toHaveText("Exam ended")
  // not banned for tab leaves: Home shows the exam as submitted, no Start button
  await page.getByRole("link", { name: "Back to my exams" }).click()
  await expect(page.locator("div[data-slot=card]").filter({ hasText: "GLOBX Full-Stack Screening" })).not.toContainText("Locked")
})

test("a leave shorter than one second is ignored", async ({ page }) => {
  await startProctoredExam(page, "sneha")
  await leaveTabFor(page, 300)
  await page.waitForTimeout(1500)
  await expect(page.getByTestId("violations")).toHaveText("Warnings 0 / 3")
})

test("5th face incident terminates the exam and locks the login", async ({ page }) => {
  await startProctoredExam(page, "amit")
  for (const n of [1, 2, 3, 4]) {
    await setFaces(page, n % 2 ? 0 : 2)          // alternate no face / two faces
    await expect(page.getByText(`Warning ${n} of 5`)).toBeVisible({ timeout: 15_000 })
    await page.getByRole("button", { name: "I understand, continue" }).click()
    await setFaces(page, 1)                      // the incident ends; the next one counts separately
    await expect(page.getByTestId("camera-box")).toContainText("Face OK")
  }
  await shot(page, "exam-face-4")
  await setFaces(page, 0)
  await expect(page).toHaveURL(/\/exam\/done\/.*why=ban/, { timeout: 15_000 })
  await expect(page.getByTestId("done-title")).toHaveText("Exam terminated")
  await shot(page, "exam-terminated")

  await page.getByRole("link", { name: "Back to my exams" }).click()
  const card = page.locator("div[data-slot=card]").filter({ hasText: "GLOBX Full-Stack Screening" })
  await expect(card).toContainText("Locked")
  await expect(card.getByRole("link", { name: /Start|Resume/ })).toHaveCount(0)
})
