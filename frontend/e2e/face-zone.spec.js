import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// The face box and the oval: the candidate sees a box on the face and a green oval to stay in, the exam author sets the oval's size (with a
// preview), and a face that stays outside the oval counts as a face warning. The detector is pinned by the dev-only hooks
// window.__faceCount (how many faces) and window.__faceAt (where the first face's middle is, 0 to 1 across and down).
const setFaces = (page, n) => page.evaluate((v) => { window.__faceCount = v }, n)
const faceAt = (page, x, y) => page.evaluate((v) => { window.__faceAt = v }, [x, y])
const guide = (page) => page.getByTestId("face-guide")

async function makeExam(api, title, zone) {
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, shuffle_questions: false, shuffle_options: false,
    settings: { proctoring: { enabled: true, webcam: true, fullscreen: false, block_multi_display: false, face_zone: zone } } })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} Q1`, body: "<p>Question 1</p>", marks: 1,
    config: { options: [{ id: "a", text: "Yes", correct: true }, { id: "b", text: "No", correct: false }] } })
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

// Signs the candidate in and opens the check-in page with the camera on and one face in the middle.
async function checkIn(page, api, exam, name) {
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: [name] })).participants[0]
  await page.addInitScript(() => { window.__faceCount = 1 })
  await page.goto("/login")
  await page.getByLabel("Username or email").fill(p.username)
  await page.getByLabel("Password", { exact: true }).fill(p.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.locator("div[data-slot=card]").filter({ hasText: exam.title }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Enable camera" }).click()
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected", { timeout: 15_000 })
  await page.getByLabel(/I understand and agree/).click()
}

test("exam setup: the author sets the oval's size with a preview, within a minimum and a maximum", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/exams/new")
  await page.getByLabel("Title", { exact: true }).fill("E2E Zone Setup")
  const setup = page.getByTestId("zone-setup")
  const slider = page.locator("#p-zone")
  await expect(slider).toHaveValue("70")                                              // the default
  await expect(guide(setup)).toHaveAttribute("data-zone", "70")
  await expect(setup.getByTestId("face-box")).toHaveCount(1)                          // the sample face
  await expect(slider).toHaveAttribute("min", "40")
  await expect(slider).toHaveAttribute("max", "100")
  await slider.press("Home")                                                          // the slider cannot go below the smallest size or above the whole picture
  await expect(slider).toHaveValue("40")
  await slider.press("ArrowLeft")
  await expect(slider).toHaveValue("40")
  await expect(guide(setup)).toHaveAttribute("data-zone", "40")
  await slider.press("End")
  await expect(slider).toHaveValue("100")
  await slider.press("ArrowRight")
  await expect(slider).toHaveValue("100")
  await slider.fill("55")
  await expect(setup).toContainText("55% of the camera picture")
  await expect(guide(setup)).toHaveAttribute("data-zone", "55")
  await shot(page, "face-zone-setup")

  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}/)
  await page.getByRole("tab", { name: "Details" }).click()
  await page.reload()
  await expect(page.locator("#p-zone")).toHaveValue("55")                             // saved with the exam
  await page.getByLabel("Camera and face check").click()                              // no camera rule, no oval to set
  await expect(page.getByTestId("zone-setup")).toHaveCount(0)
})

test("candidate: a box follows the face, the oval is drawn, a face outside it blocks Start, two faces show two boxes", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Zone Check-in", 50)
  await checkIn(page, api, exam, "Zara Oval")
  await expect(guide(page)).toHaveAttribute("data-zone", "50")                        // the exam's own size
  await expect(guide(page)).toHaveAttribute("data-state", "ok")
  await expect(guide(page).getByTestId("face-oval")).toBeVisible()
  await expect(guide(page).getByTestId("face-box")).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
  await shot(page, "face-zone-checkin-ok")

  await faceAt(page, 0.8, 0.5)                                                        // the middle of the face is outside a 50% oval
  await expect(page.getByTestId("face-status")).toHaveText("Move your face into the oval")
  await expect(guide(page)).toHaveAttribute("data-state", "off")
  await expect(guide(page).getByTestId("face-box")).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await shot(page, "face-zone-checkin-off")

  await faceAt(page, 0.6, 0.55)                                                       // near the edge but inside: fine
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected")
  await setFaces(page, 2)
  await expect(guide(page).getByTestId("face-box")).toHaveCount(2)
  await expect(guide(page)).toHaveAttribute("data-state", "many")
  await expect(page.getByTestId("face-status")).toHaveText("2 faces detected")
  await setFaces(page, 0)
  await expect(guide(page).getByTestId("face-box")).toHaveCount(0)
  await expect(page.getByTestId("face-status")).toHaveText("No face detected")
  await setFaces(page, 1)
  await faceAt(page, 0.5, 0.5)
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })

  await page.setViewportSize({ width: 360, height: 800 })                             // the phone: nothing runs off the side
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, "face-zone-checkin-phone")
})

test("exam: staying outside the oval for the grace time is a face warning; coming back clears it", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Zone Exam", 50)
  await checkIn(page, api, exam, "Yash Oval")
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)
  const box = page.getByTestId("camera-box")
  await expect(box).toContainText("Face OK")
  await expect(box.getByTestId("face-box")).toHaveCount(1)
  await expect(guide(box)).toHaveAttribute("data-zone", "50")
  await shot(page, "face-zone-exam-ok")

  await faceAt(page, 0.8, 0.5)
  await expect(box).toContainText("Move to the centre")                              // at once on screen, and a warning after the 3 seconds
  await expect(guide(box)).toHaveAttribute("data-state", "off")
  await expect(page.getByText("Warning 1 of 5")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/inside the oval/)).toBeVisible()
  await shot(page, "face-zone-exam-warning")
  await page.getByRole("button", { name: "I understand, continue" }).click()
  await faceAt(page, 0.5, 0.5)
  await expect(box).toContainText("Face OK")
  await expect(box).toContainText("1/5")

  // a short move out and back (under the grace time) is not counted
  await faceAt(page, 0.85, 0.5)
  await page.waitForTimeout(1200)
  await faceAt(page, 0.5, 0.5)
  await page.waitForTimeout(4500)
  await expect(box).toContainText("1/5")
})

test("the whole picture (100%) still has round corners: a face in the far corner is outside, one at the side is inside", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Zone Full", 100)
  await checkIn(page, api, exam, "Full Frame")
  await faceAt(page, 0.93, 0.5)
  await expect(guide(page)).toHaveAttribute("data-state", "ok")
  await faceAt(page, 0.9, 0.9)
  await expect(guide(page)).toHaveAttribute("data-state", "off")
})
