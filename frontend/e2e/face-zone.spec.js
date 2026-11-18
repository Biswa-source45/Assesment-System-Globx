import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest } from "./helpers"

// The face box and the oval: the candidate sees a box on the face and a green oval to stay in, the exam author sets the oval's size (with a
// preview), and a face that stays outside the oval counts as a face warning. The detector is pinned by the dev-only hooks
// window.__faceCount (how many faces) and window.__faceAt (where the first face's middle is, 0 to 1 across and down).
const setFaces = (page, n) => page.evaluate((v) => { window.__faceCount = v }, n)
const faceAt = (page, x, y) => page.evaluate((v) => { window.__faceAt = v }, [x, y])
const guide = (page) => page.getByTestId("face-guide")
const facePose = (page, yaw, pitch) => page.evaluate((v) => { window.__facePose = v }, [yaw, pitch])
const covered = (page, on) => page.evaluate((v) => { window.__faceCovered = v }, on)

async function makeExam(api, title, zone, extra = {}) {
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, shuffle_questions: false, shuffle_options: false,
    settings: { proctoring: { enabled: true, webcam: true, fullscreen: false, block_multi_display: false, face_zone: zone, ...extra } } })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} Q1`, body: "<p>Question 1</p>", marks: 1,
    config: { options: [{ id: "a", text: "Yes", correct: true }, { id: "b", text: "No", correct: false }] } })
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

// Signs the candidate in and opens the check-in page with the camera on and one face in the middle.
async function checkIn(page, api, exam, name, pose) {
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: [name] })).participants[0]
  await page.addInitScript(() => { window.__faceCount = 1 })
  if (pose) await page.addInitScript((v) => { window.__facePose = v }, pose)
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

test("exam setup: where the candidate may look, each direction with its own limit, saved with the exam", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/exams/new")
  await page.getByLabel("Title", { exact: true }).fill("E2E Look Setup")
  const setup = page.getByTestId("look-setup")
  for (const d of ["left", "right", "up", "down"]) {                                  // nothing is checked until the author switches it on
    await expect(page.locator(`#look-${d}`)).not.toBeChecked()
    await expect(page.locator(`#look-${d}-deg`)).toHaveCount(0)
  }
  await expect(page.locator("#p-hand")).not.toBeChecked()
  await page.locator("#look-left").click()
  await expect(page.locator("#look-left-deg")).toHaveValue("30")                      // starts at 30 degrees
  await expect(page.getByTestId("look-left-value")).toHaveText("up to 30°")
  await page.locator("#look-left-deg").press("Home")
  await expect(page.getByTestId("look-left-value")).toHaveText("up to 10°")           // the smallest limit
  await page.locator("#look-left-deg").press("ArrowLeft")
  await expect(page.getByTestId("look-left-value")).toHaveText("up to 10°")
  await page.locator("#look-down").click()
  await page.locator("#look-down-deg").press("End")
  await expect(page.getByTestId("look-down-value")).toHaveText("up to 60°")           // the largest
  await page.locator("#p-hand").click()
  await shot(page, "face-zone-look-setup")
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}/)
  await page.getByRole("tab", { name: "Details" }).click()
  await page.reload()
  await expect(page.getByTestId("look-left-value")).toHaveText("up to 10°")
  await expect(page.getByTestId("look-down-value")).toHaveText("up to 60°")
  await expect(page.locator("#look-right")).not.toBeChecked()
  await expect(page.locator("#p-hand")).toBeChecked()
  await page.locator("#look-left").click()                                            // switching a direction off keeps it off
  await page.getByRole("button", { name: "Save exam" }).click()
  await expect(page.getByText("Exam saved")).toBeVisible()
  await page.reload()
  await expect(page.locator("#look-left")).not.toBeChecked()
  await expect(page.getByTestId("look-down-value")).toHaveText("up to 60°")
  await page.getByLabel("Camera and face check").click()                              // no camera rule, no look rules to set
  await expect(setup).toHaveCount(0)
})

test("check-in: turning left or down, or covering the face, blocks Start; a direction that is not checked does not", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Look Check-in", 100, { look: { left: 20, down: 20 }, hand_on_face: true })
  await checkIn(page, api, exam, "Lena Look")
  await expect(page.getByText(/do not turn your head left, down/)).toBeVisible()
  await expect(page.getByText(/do not cover your face with your hand/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
  await facePose(page, 30, 0)                                                         // 30 degrees to the left (positive: the candidate's own left), 20 allowed
  await expect(page.getByTestId("face-status")).toHaveText("Looking left: look at the screen")
  await expect(guide(page)).toHaveAttribute("data-state", "left")
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await shot(page, "face-zone-checkin-left")
  await facePose(page, 15, 0)                                                         // inside the limit
  await expect(page.getByTestId("face-status")).toHaveText("1 face detected")
  await facePose(page, -40, 0)                                                        // right is not checked
  await expect(guide(page)).toHaveAttribute("data-state", "ok")
  await facePose(page, 0, -40)                                                        // nor is up
  await expect(guide(page)).toHaveAttribute("data-state", "ok")
  await facePose(page, 0, 25)
  await expect(page.getByTestId("face-status")).toHaveText("Looking down: look at the screen")
  await expect(guide(page)).toHaveAttribute("data-state", "down")
  await covered(page, true)
  await expect(page.getByTestId("face-status")).toHaveText("Face covered: take your hand away")
  await expect(guide(page)).toHaveAttribute("data-state", "hand")
  await expect(page.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await covered(page, false)
  await facePose(page, 0, 0)
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
})

test("check-in: the limit is measured from how the candidate sits, and a candidate who starts turned away is asked to look straight", async ({ page, request, browser }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Look Neutral", 100, { look: { down: 20 } })
  await checkIn(page, api, exam, "Nora Neutral", [0, 20])                             // a laptop camera below the eyes: straight is 20 degrees
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })  // the first three looks are done: their own "straight" is known
  await facePose(page, 0, 38)                                                       // 18 further down than their own straight: fine
  await expect(guide(page)).toHaveAttribute("data-state", "ok")
  await facePose(page, 0, 45)                                                         // 25 further: too far
  await expect(guide(page)).toHaveAttribute("data-state", "down")

  const other = await makeExam(api, "E2E Look Straight", 100, { look: { left: 30 } })
  const { page: page2 } = await candidateWindow(browser)
  await checkIn(page2, api, other, "Sam Sideways", [40, 0])                           // already turned 40 degrees when the camera starts
  await expect(page2.getByTestId("face-status")).toHaveText("Look straight at the screen", { timeout: 10_000 })
  await expect(page2.getByRole("button", { name: "Start exam" })).toBeDisabled()
  await page2.evaluate(() => { window.__facePose = [5, 0] })
  await expect(page2.getByTestId("face-status")).toHaveText("1 face detected")
  await expect(page2.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
})

test("exam: staying turned away is a face warning that names the direction; the review timeline shows it; an exam without the rules ignores it", async ({ page, request, browser }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Look Exam", 100, { look: { left: 20 }, hand_on_face: true })
  await checkIn(page, api, exam, "Omar Look")
  await expect(page.getByRole("button", { name: "Start exam" })).toBeEnabled({ timeout: 5_000 })
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)
  const attempt = page.url().split("/").pop()
  const box = page.getByTestId("camera-box")
  await expect(box).toContainText("Face OK")
  await facePose(page, 30, 0)
  await expect(box).toContainText("Looking left!")
  await expect(guide(box)).toHaveAttribute("data-state", "left")
  await expect(page.getByText("Warning 1 of 5")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/uncovered and looking at the screen/)).toBeVisible()
  await shot(page, "face-zone-exam-left")
  await page.getByRole("button", { name: "I understand, continue" }).click()
  await facePose(page, 0, 0)
  await expect(box).toContainText("Face OK")
  await covered(page, true)
  await expect(box).toContainText("Face covered!")
  await expect(page.getByText("Warning 2 of 5")).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: "I understand, continue" }).click()
  await covered(page, false)
  await expect(box).toContainText("2/5")
  const events = (await api.get(`/reports/attempts/${attempt}`)).proctoring.events
  expect(events.filter((e) => e.type === "face_turned").map((e) => e.direction)).toEqual(["left"])
  expect(events.filter((e) => e.type === "hand_on_face")).toHaveLength(1)

  // an exam that never switched the rules on: the same turn and cover are ignored, and nothing extra is asked of the candidate
  const plain = await makeExam(api, "E2E Look Off", 100)
  const { page: page2 } = await candidateWindow(browser)
  await checkIn(page2, api, plain, "Pia Plain")
  await expect(page2.getByText(/do not turn your head/)).toHaveCount(0)
  await facePose(page2, -60, 50)
  await covered(page2, true)
  await expect(page2.getByTestId("face-status")).toHaveText("1 face detected")
  await expect(guide(page2)).toHaveAttribute("data-state", "ok")
})
