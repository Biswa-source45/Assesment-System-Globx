import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// Minimum reading time: a question has to stay on screen N seconds the first time it is opened before any way of moving
// forward unlocks. Real screens, no camera (proctoring off), so only this rule is in play.
const SECONDS = 4

async function makeExam(api, title, settings, sectionSizes = [3, 1]) {
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, shuffle_questions: false, shuffle_options: false, settings: { proctoring: { enabled: false }, ...settings } })
  let n = 0
  for (const [i, size] of sectionSizes.entries()) {
    const section = (await api.post(`/tests/${exam.id}/sections`, { title: `Part ${"AB"[i]}` })).sections[i]
    for (let k = 0; k < size; k++) {
      n++
      const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} Q${n}`, body: `<p>Question ${n}</p>`, marks: 1,
        config: { options: [{ id: "a", text: `Yes ${n}`, correct: true }, { id: "b", text: `No ${n}`, correct: false }] } })
      await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
    }
  }
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

async function person(api, exam, name) { return (await api.post(`/tests/${exam.id}/participants`, { names: [name] })).participants[0] }

async function open(page, p, title) {
  await page.goto("/login")
  await page.getByLabel("Username or email").fill(p.username)
  await page.getByLabel("Password", { exact: true }).fill(p.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.locator("div[data-slot=card]").filter({ hasText: title }).getByRole("link", { name: /Start|Resume/ }).click()
}
async function begin(page) {
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)
}

const next = (page) => page.getByRole("button", { name: /^(Save and next|Next section|Finish)/ })

test("every way forward is locked until the question has been on screen long enough; going back is free", async ({ page, request }) => {
  const api = await staffRequest(request)
  const title = "E2E Read Time"
  const exam = await makeExam(api, title, { min_question_seconds: SECONDS })
  const p = await person(api, exam, "Read Quickly")

  await open(page, p, title)
  await expect(page.getByText(`at least ${SECONDS} seconds`)).toBeVisible()  // said before the exam starts
  await begin(page)

  // question 1: everything that moves forward is locked, with a countdown; answering does not unlock it
  await expect(page.getByRole("button", { name: new RegExp(`^Save and next \\(\\ds\\)$`) })).toBeDisabled()
  await expect(page.getByTestId("read-hint")).toContainText("Next unlocks in")
  await expect(page.getByRole("button", { name: "Question 3" })).toBeDisabled()
  await expect(page.getByRole("button", { name: /^Part B/ })).toBeDisabled()
  await page.getByRole("radio", { name: "Yes 1" }).click()
  await expect(next(page)).toBeDisabled()
  // what must keep working: marking for review, ending the exam, the current question's own number
  await expect(page.getByRole("button", { name: "Mark for review" })).toBeEnabled()
  await expect(page.getByRole("button", { name: "End exam" })).toBeEnabled()
  await expect(page.getByRole("button", { name: "Question 1" })).toBeEnabled()
  await shot(page, "read-time-locked")

  // it unlocks by itself and Next moves on; question 2 starts its own wait
  await expect(next(page)).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })
  await expect(page.getByTestId("read-hint")).toHaveCount(0)
  await next(page).click()
  await expect(page.getByRole("heading", { name: `${title} Q2` })).toBeVisible()
  await expect(next(page)).toBeDisabled()

  // going back is never locked, and a question that had its time is free forever
  await page.getByRole("button", { name: "Previous" }).click()
  await expect(page.getByRole("heading", { name: `${title} Q1` })).toBeVisible()
  await expect(next(page)).toBeEnabled({ timeout: 500 })
  await next(page).click()
  await expect(next(page)).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })  // Q2 finishes its wait
  await next(page).click()

  // question 3 is the last of section A: the button is "Next section", locked the same way
  await expect(page.getByRole("heading", { name: `${title} Q3` })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Next section \(\ds\)$/ })).toBeDisabled()
  await page.getByRole("button", { name: "Question 1" }).click()  // an earlier number is allowed
  await expect(page.getByRole("heading", { name: `${title} Q1` })).toBeVisible()
  await page.getByRole("button", { name: "Question 3" }).click()  // and the way back to 3 is open: it is the question being left, 1 had its time
  await expect(page.getByRole("heading", { name: `${title} Q3` })).toBeVisible()
  await expect(next(page)).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })
  await next(page).click()

  // section B has one question, which is also the last one: Finish is locked, then opens the end dialog
  await expect(page.getByRole("heading", { name: `${title} Q4` })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Finish \(\ds\)$/ })).toBeDisabled()
  await expect(page.getByRole("button", { name: /^Part A/ })).toBeEnabled()  // an earlier section tab is allowed
  await expect(next(page)).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })
  await next(page).click()
  await expect(page.getByRole("dialog")).toContainText("You cannot return after submitting.")
})

test("after a reload, questions already answered are free and an unanswered one waits again", async ({ page, request }) => {
  const api = await staffRequest(request)
  const title = "E2E Read Reload"
  const exam = await makeExam(api, title, { min_question_seconds: SECONDS }, [3])
  const p = await person(api, exam, "Read Reload")
  await open(page, p, title)
  await begin(page)

  const answer = async (name) => {  // click an option and wait until the server has it
    const saved = page.waitForResponse((r) => r.request().method() === "PUT" && /\/answers\//.test(r.url()))
    await page.getByRole("radio", { name }).click()
    await saved
  }
  await answer("Yes 1")
  await expect(next(page)).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })
  await next(page).click()
  await answer("Yes 2")

  await page.reload()  // the screen restarts at question 1
  await expect(page.getByRole("heading", { name: `${title} Q1` })).toBeVisible()
  await expect(next(page)).toBeEnabled({ timeout: 500 })  // answered earlier: no new wait
  await next(page).click()
  await expect(next(page)).toBeEnabled({ timeout: 500 })  // question 2 too
  await next(page).click()
  await expect(page.getByRole("heading", { name: `${title} Q3` })).toBeVisible()
  await expect(page.getByRole("button", { name: /^Finish \(\ds\)$/ })).toBeDisabled()  // never opened: it waits
  await expect(page.getByRole("button", { name: /^Finish$/ })).toBeEnabled({ timeout: SECONDS * 1000 + 3000 })
})

test("with the setting off there is no wait and no line at check-in", async ({ page, request }) => {
  const api = await staffRequest(request)
  const title = "E2E Read Off"
  const exam = await makeExam(api, title, {}, [2])
  const p = await person(api, exam, "Read Off")
  await open(page, p, title)
  await expect(page.getByText(/seconds before you can move on/)).toHaveCount(0)
  await begin(page)
  await expect(page.getByTestId("read-hint")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Save and next", exact: true })).toBeEnabled({ timeout: 500 })
  await expect(page.getByRole("button", { name: "Question 2" })).toBeEnabled()
})

test("the exam form: a new exam starts at 5, a saved value is kept, a silly value is cut to 0..60", async ({ page, request }) => {
  await loginStaff(page)
  await page.goto("/admin/exams/new")
  await expect(page.getByLabel("Seconds each question stays on screen before Next unlocks")).toHaveValue("5")
  await page.getByLabel("Title", { exact: true }).fill("E2E Read Form")
  await page.getByLabel("Seconds each question stays on screen before Next unlocks").fill("7")
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}/)
  const id = page.url().match(/exams\/([0-9a-f]{32})/)[1]
  await page.getByRole("tab", { name: "Details" }).click()
  await page.reload()
  const field = page.getByLabel("Seconds each question stays on screen before Next unlocks")
  await expect(field).toHaveValue("7")
  await field.fill("999")  // the browser itself refuses a value above 60: nothing is saved
  await page.getByRole("button", { name: "Save exam" }).click()
  expect(await field.evaluate((i) => i.validity.valid)).toBe(false)
  await expect(page.getByText("Exam saved")).toHaveCount(0)
  const api = await staffRequest(request)
  expect((await api.get(`/tests/${id}`)).settings.min_question_seconds).toBe(7)
  await field.fill("60")
  await page.getByRole("button", { name: "Save exam" }).click()
  await expect.poll(async () => (await api.get(`/tests/${id}`)).settings.min_question_seconds).toBe(60)
  await field.fill("")
  await page.getByRole("button", { name: "Save exam" }).click()
  await expect.poll(async () => (await api.get(`/tests/${id}`)).settings.min_question_seconds).toBe(0)  // empty means off
})
