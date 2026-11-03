import { expect, test } from "@playwright/test"
import { BASE_URL, login, loginStaff, shot, staffRequest } from "./helpers"

const dialog = (page) => page.getByRole("dialog")
const PIXEL = Buffer.from("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=", "base64")

// The people taking an exam, driven through the API: much faster than clicking, and the same server rules.
async function candidate(request, username, password) {
  const auth = await (await request.post("/api/v1/auth/login", { data: { email: username, password } })).json()
  const headers = { Authorization: "Bearer " + auth.access_token }
  const call = async (method, path, data) => {
    const r = await request[method](`/api/v1${path}`, { headers, data })
    expect(r.ok(), `${method} ${path}: ${await r.text()}`).toBeTruthy()
    return r.json()
  }
  return {
    get: (p) => call("get", p), post: (p, d) => call("post", p, d), put: (p, d) => call("put", p, d),
    picture: (at, faces) => request.post(`/api/v1/attempts/${at}/proctor/snapshot`, { headers, multipart: { kind: "webcam", faces: String(faces), image: { name: "p.jpg", mimeType: "image/jpeg", buffer: PIXEL } } }),
  }
}

async function makeExam(api, title, { text = true, cutoff = 5 } = {}) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = (body) => api.post("/questions", { department_id: dept, body: "<p>x</p>", ...body })
  const made = [await q({ type: "mcq_single", title: `${title} mcq`, marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })]
  if (text) {
    made.push(await q({ type: "short", title: `${title} short`, marks: 2, config: { model_answer: "alpha is first", keywords: ["alpha"], max_words: 100 } }))
    made.push(await q({ type: "long", title: `${title} long`, marks: 5, config: { model_answer: "an explanation", rubric: [{ id: "r1", name: "Content", max: 3 }, { id: "r2", name: "Clarity", max: 2 }] } }))
  }
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, cutoff, shuffle_questions: false, shuffle_options: false })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  for (const x of made) await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: x.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

async function person(api, request, examId, name) {
  const p = (await api.post(`/tests/${examId}/participants`, { names: [name] })).participants[0]
  return { ...p, api: await candidate(request, p.username, p.password) }
}

// Starts the exam, saves the answers (kind = the last word of the question title), and submits unless `leave`.
async function sit(c, answers, { leave = false } = {}) {
  const { attempt_id: at } = await c.api.post(`/assignments/${c.assignment_id}/start`, { consent: { accepted: true }, system_check: {} })
  const state = await c.api.get(`/attempts/${at}`)
  const byKind = Object.fromEntries(state.sections.flatMap((s) => s.questions).map((x) => [x.title.split(" ").pop(), x.id]))
  let seq = 0
  for (const [kind, response] of Object.entries(answers)) await c.api.put(`/attempts/${at}/answers/${byKind[kind]}`, { response, flagged: false, seq: ++seq })
  c.attempt = at
  if (!leave) await c.api.post(`/attempts/${at}/submit`, {})
}

const finished = (c) => expect.poll(async () => (await c.api.get(`/attempts/${c.attempt}`)).attempt.status, { timeout: 30_000 }).toMatch(/review_pending|evaluated/)
const closeExam = (api, exam, cutoff = 5) => api.send("put", `/tests/${exam.id}`, {
  department_id: exam.department_id, title: exam.title, duration_min: 30, cutoff, shuffle_questions: false, shuffle_options: false, ends_at: new Date(Date.now() - 60_000).toISOString(),
})
const myResult = async (c) => (await c.api.get("/me/assignments")).find((a) => a.assignment_id === c.assignment_id).result

test("results: calculated by itself after the end time, reviewed, declared; ended and absent candidates are recorded", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Results Exam")
  const asha = await person(api, request, exam.id, "Asha Finisher")
  const bala = await person(api, request, exam.id, "Bala Terminated")
  await person(api, request, exam.id, "Chitra Absent")
  await sit(asha, { mcq: { selected: ["a"] }, short: { html: "<p>alpha beta</p>" }, long: { html: "<p>a clear explanation</p>" } })
  await sit(bala, { mcq: { selected: ["b"] }, short: { html: "<p>no idea</p>" }, long: { html: "<p>too short</p>" } }, { leave: true })
  await bala.api.picture(bala.attempt, 0)  // the camera saw nobody once
  for (let i = 0; i < 4; i++) await bala.api.post(`/attempts/${bala.attempt}/proctor/events`, { events: [{ type: "tab_blur", duration_ms: 2000 }] })  // the fourth ends the exam
  await finished(asha)
  await finished(bala)

  await loginStaff(page, "evaluator@globx.co.in")
  await page.goto("/admin/results")
  await expect(page.getByTestId("results-exam").filter({ hasText: "E2E Results Exam" })).toContainText("Open")  // no end time has passed yet

  // the end time passes: nobody presses anything, the exam is calculated
  expect((await closeExam(api, exam)).ok()).toBeTruthy()
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Needs attention", { timeout: 45_000 })
  const row = (name) => page.getByTestId("results-row").filter({ hasText: name })
  await expect(row("Asha Finisher")).toContainText("Submitted")
  await expect(row("Bala Terminated")).toContainText("Ended: left the window too often")
  await expect(row("Chitra Absent")).toContainText("Did not attend")
  await expect(page.getByTestId("summary-Appeared")).toHaveText("2")
  await expect(page.getByTestId("summary-Did not attend")).toHaveText("1")
  await expect(page.getByTestId("summary-Ended early")).toHaveText("1")
  await expect(page.getByRole("button", { name: "Declare results" })).toBeDisabled()  // marks are waiting for a person
  await shot(page, "results-needs-attention")

  // accept what has a suggestion (the keyword marks of the short answers); the explained answers need a person
  await page.getByRole("button", { name: "Accept all suggested marks" }).click()
  await dialog(page).getByRole("button", { name: "Accept", exact: true }).click()
  await expect(row("Asha Finisher").getByRole("cell").nth(6)).toHaveText("1")  // her explained answer is still waiting
  await expect(page.getByTestId("results-banner")).toContainText("2 answer(s) need your attention")

  // review Asha: her answer is shown, and the explained answer is marked by hand
  await row("Asha Finisher").getByRole("link", { name: "Review" }).click()
  await expect(page.getByTestId("review-question")).toHaveCount(3)
  await expect(page.getByTestId("answer-text").filter({ hasText: "a clear explanation" })).toBeVisible()
  // right and wrong are visible at a glance: the option she ticked is green and marked correct, the other is plain
  const mcq = page.getByTestId("review-question").filter({ hasText: "Exam mcq" })
  await expect(mcq).toHaveAttribute("data-verdict", "good")
  await expect(mcq.getByTestId("verdict")).toHaveText("Correct")
  await expect(mcq.locator("[data-state=chosen-right]")).toContainText("Chosen. Correct")
  await expect(mcq.locator("[data-state=plain]")).toHaveCount(1)
  const short = page.getByTestId("review-question").filter({ hasText: "Exam short" })
  await expect(short.getByTestId("model-answer")).toHaveText("alpha is first")
  await expect(short.locator("[data-state=found]")).toHaveText("alpha")  // the word she was expected to mention is there
  await expect(page.getByTestId("needs-attention")).toHaveCount(1)
  await page.getByTestId("review-question").filter({ hasText: "Exam long" }).getByRole("button", { name: "Mark or change the mark" }).click()
  await dialog(page).getByLabel("Mark", { exact: true }).fill("4")
  await dialog(page).getByRole("button", { name: "Save mark" }).click()
  await expect(page.getByTestId("needs-attention")).toHaveCount(0)
  await expect(page.getByTestId("review-Score")).toHaveText("7 / 8")  // 1 + 2 + 4
  await expect(page.getByTestId("review-Percent")).toHaveText("87.5%")
  await expect(page.getByTestId("review-Result")).toHaveText("Passed")
  await shot(page, "results-review")

  // review Bala: what the proctoring saw, and a mark that needs a reason when it differs from the suggestion
  await page.goBack()
  await row("Bala Terminated").getByRole("link", { name: "Review" }).click()
  await expect(page.getByTestId("timeline")).toContainText("tab blur (2 s)")
  await expect(page.getByTestId("pictures")).toContainText("0 face(s)")
  await expect(page.getByTestId("review-Result")).toHaveText("Not passed")
  const wrong = page.getByTestId("review-question").filter({ hasText: "Exam mcq" })
  await expect(wrong).toHaveAttribute("data-verdict", "bad")
  await expect(wrong.getByTestId("verdict")).toHaveText("Wrong")
  await expect(wrong.locator("[data-state=chosen-wrong]")).toContainText("Chosen. Wrong")  // what he ticked: red
  await expect(wrong.locator("[data-state=missed-right]")).toContainText("The correct answer (not chosen)")  // what was right: green
  await expect(page.getByTestId("review-question").filter({ hasText: "Exam short" }).locator("[data-state=missing]")).toHaveText("alpha")
  await shot(page, "results-review-wrong")
  await page.getByTestId("review-question").filter({ hasText: "Exam short" }).getByRole("button", { name: "Mark or change the mark" }).click()
  await dialog(page).getByLabel("Mark", { exact: true }).fill("1")
  await dialog(page).getByRole("button", { name: "Save mark" }).click()
  await expect(dialog(page)).toContainText("override reason is required")  // the server's rule, in the dialog
  await dialog(page).getByLabel("Reason for changing the mark").fill("said something relevant")
  await dialog(page).getByRole("button", { name: "Save mark" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await page.getByTestId("review-question").filter({ hasText: "Exam long" }).getByRole("button", { name: "Mark or change the mark" }).click()
  await dialog(page).getByLabel("Mark", { exact: true }).fill("1")
  await dialog(page).getByRole("button", { name: "Save mark" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByTestId("review-Score")).toHaveText("2 / 8")  // 0 + 1 + 1

  // now it can be declared; nobody saw a result before
  expect(await myResult(asha)).toBeNull()
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare")
  await page.getByRole("button", { name: "Declare results" }).click()
  await dialog(page).getByRole("button", { name: "Declare", exact: true }).click()
  await expect(page.getByTestId("results-state")).toHaveText("Declared")
  await shot(page, "results-declared")
  const mine = await myResult(asha)
  expect([mine.score, mine.max, mine.percent, mine.result]).toEqual([7, 8, 87.5, "passed"])
  expect((await myResult(bala)).result).toBe("not_passed")

  // Asha sees it on her own home page
  const ctx = await browser.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true })
  const home = await ctx.newPage()
  await login(home, asha.username, asha.password)
  const card = home.locator("div[data-slot=card]").filter({ hasText: "E2E Results Exam" })
  await expect(card.getByTestId("my-score")).toHaveText("7 / 8 (87.5%)")
  await expect(card).toContainText("Passed")
  await expect(card).toContainText("Result declared")
  await shot(home, "results-candidate-home")
  await ctx.close()

  // withdrawing hides it again
  await page.getByRole("button", { name: "Withdraw results" }).click()
  await dialog(page).getByRole("button", { name: "Withdraw", exact: true }).click()
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare")
  expect(await myResult(asha)).toBeNull()
})

test("no end time: the results are calculated by pressing a button; each role sees only its own buttons", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Manual Results Exam", { text: false })
  const dev = await person(api, request, exam.id, "Dev Finisher")
  await sit(dev, { mcq: { selected: ["a"] } })
  await finished(dev)

  await loginStaff(page, "evaluator@globx.co.in")
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Open")
  await expect(page.getByTestId("results-banner")).toContainText("no end time")
  await expect(page.getByRole("button", { name: "CSV" })).toHaveCount(0)  // an evaluator cannot export
  await page.getByRole("button", { name: "Calculate results" }).click()
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare", { timeout: 30_000 })  // nothing needed a person
  await expect(page.getByTestId("results-row").filter({ hasText: "Dev Finisher" })).toContainText("1 / 1")
  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)

  await loginStaff(page, "recruiter@globx.co.in")  // a recruiter can look and export, not calculate or declare
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare")
  for (const name of ["Calculate again", "Declare results", "Accept all suggested marks"]) await expect(page.getByRole("button", { name })).toHaveCount(0)
  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: "CSV" }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/results\.csv$/)
  const text = (await (await import("node:fs")).promises.readFile(await file.path(), "utf8"))
  expect(text.split("\n")[0]).toContain("Outcome")
  expect(text).toContain("Dev Finisher")
  await page.goto("/admin/results")
  await expect(page.getByTestId("results-exam").filter({ hasText: "E2E Manual Results Exam" })).toContainText("Ready to declare")
})

test("a blank paper is never shown as passed, and an exam without a pass mark shows scores without a verdict", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const exam = await makeExam(api, "E2E Blank Exam", { text: false, cutoff: 0 })  // pass mark 0: the case that showed a blank paper as "Passed"
  const blank = await person(api, request, exam.id, "Blank Paper")
  const some = await person(api, request, exam.id, "Some Answers")
  await sit(blank, {})
  await sit(some, { mcq: { selected: ["a"] } })
  await finished(blank)
  await finished(some)
  expect((await closeExam(api, exam, 0)).ok()).toBeTruthy()

  await loginStaff(page, "evaluator@globx.co.in")
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare", { timeout: 45_000 })
  const row = (name) => page.getByTestId("results-row").filter({ hasText: name })
  await expect(row("Blank Paper")).toContainText("Did not attempt")
  await expect(row("Blank Paper")).not.toContainText("Passed")
  await expect(row("Some Answers")).toContainText("No pass mark set")      // a score of 1 / 1, but no verdict without a pass mark
  await expect(page.getByTestId("summary-Passed")).toHaveText("0")
  await expect(page.getByTestId("summary-Did not attempt")).toHaveText("1")

  // the review of the blank paper: red "Did not attempt", and the answer key is shown without green marks
  await row("Blank Paper").getByRole("link", { name: "Review" }).click()
  await expect(page.getByTestId("review-Result")).toHaveText("Did not attempt")
  const mcq = page.getByTestId("review-question").filter({ hasText: "Blank Exam mcq" })
  await expect(mcq.locator("[data-state=answer-key]")).toContainText("Correct answer")
  await expect(mcq.locator("[data-state=missed-right]")).toHaveCount(0)
  await expect(mcq.locator("[data-state=chosen-right]")).toHaveCount(0)
  await shot(page, "results-blank-paper")
  await page.goBack()
  await row("Some Answers").getByRole("link", { name: "Review" }).click()
  await expect(page.getByTestId("review-Result")).toHaveText("No pass mark set")
  await expect(page.getByTestId("review-Score")).toHaveText("1 / 1")

  // declared: the candidate who answered nothing is told so, with no Passed badge
  await page.goBack()
  await page.getByRole("button", { name: "Declare results" }).click()
  await dialog(page).getByRole("button", { name: /declare/i }).click()
  await expect(page.getByTestId("results-state")).toHaveText("Declared")
  const ctx = await browser.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true })
  const mine = await ctx.newPage()
  await login(mine, blank.username, blank.password)
  const card = mine.getByTestId("my-result")
  await expect(card).toContainText("You did not answer any question")
  await expect(card).toContainText("Did not attempt")
  await expect(card).not.toContainText("Passed")
  await ctx.close()
})
