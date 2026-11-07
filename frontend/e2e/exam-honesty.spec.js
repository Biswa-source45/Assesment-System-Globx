import { expect, test } from "@playwright/test"
import { candidateWindow, login, loginStaff, shot, staffRequest } from "./helpers"

// An exam without the camera check, the way the first real exam ran: the candidate types an explained answer and ticks
// multiple-answer options on the real screens; the invigilator watches the screen live; the review shows what was written
// and the multiple-answer question is marked strictly (each wrong tick takes 0.25 off, ticking everything scores 0).
const WRITTEN = "I would list my tasks, tell my manager and offer to help my colleague later."

async function examWithoutCamera(api) {
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const options = ["a", "b", "c", "d", "e"].map((k) => ({ id: k, text: `Opt ${k.toUpperCase()}`, correct: "abc".includes(k) }))  // three right of five
  const multi = await api.post("/questions", { department_id: dept, type: "mcq_multi", title: "Honesty multi", body: "<p>Tick all that apply.</p>", marks: 3, config: { options, partial: true } })
  const long = await api.post("/questions", { department_id: dept, type: "long", title: "Honesty long", body: "<p>Explain what you would do.</p>", marks: 4, config: { model_answer: "plan, tell, help", rubric: [{ id: "r1", name: "All", max: 4 }] } })
  const exam = await api.post("/tests", { department_id: dept, title: "E2E No Camera Exam", duration_min: 30, shuffle_questions: false, settings: { proctoring: { webcam: false, screen_share: true, live_view: true, evidence: "pictures" } } })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  for (const q of [multi, long]) await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

// Opens the exam as a candidate (no camera step), ticks the options and types the answer; the attempt id is returned with the open window.
async function takeExam(browser, person, ticks, written) {
  const w = await candidateWindow(browser)
  await login(w.page, person.username, person.password)
  await w.page.locator("div[data-slot=card]").filter({ hasText: "E2E No Camera Exam" }).getByRole("link", { name: /Start|Resume/ }).click()
  await expect(w.page.getByRole("button", { name: "Enable camera" })).toHaveCount(0)  // this exam has no camera step
  await w.page.getByLabel(/I understand and agree/).click()
  await w.page.getByRole("button", { name: "Accept and start exam" }).click()
  await expect(w.page).toHaveURL(/\/exam\/attempt\//)
  w.attempt = w.page.url().split("/").pop()
  for (const k of ticks) await w.page.getByRole("checkbox", { name: `Opt ${k.toUpperCase()}` }).click()
  if (written) {
    await w.page.getByRole("button", { name: "Question 2" }).click()
    await w.page.getByLabel("Your answer").fill(written)
  }
  return w
}

async function submit(w) {
  await w.page.getByRole("button", { name: "End exam" }).click()
  const box = w.page.getByRole("dialog")
  await expect(box).toContainText("You cannot return after submitting.")
  await expect(box).not.toContainText("Coding answers")  // an HR exam has no coding question
  await w.page.getByRole("button", { name: "Submit exam" }).click()
  await expect(w.page).toHaveURL(/\/exam\/done\//)
}

test("no camera: the screen is watched live, what was written and ticked is shown and marked strictly", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const exam = await examWithoutCamera(api)
  const people = {}
  for (const name of ["Rina Exact", "Rita Extra", "Rani Every"]) people[name] = (await api.post(`/tests/${exam.id}/participants`, { names: [name] })).participants[0]

  const rina = await takeExam(browser, people["Rina Exact"], ["a", "b", "c"], WRITTEN)

  // the invigilator sees Rina's screen (and no empty camera box) while she is still in the exam
  await loginStaff(page)
  await page.goto(`/admin/monitor?exam=${exam.id}`)
  await page.getByRole("button", { name: "Live view" }).click()
  const card = page.getByTestId("live-card").filter({ hasText: "Rina Exact" })
  await expect(card.getByTestId("live-state")).toHaveText("Live", { timeout: 30_000 })
  await expect(card.locator("video[data-live=yes]")).toHaveCount(1)
  await expect(card.getByLabel("Rina Exact camera")).toHaveCount(0)
  await expect.poll(() => card.getByLabel("Rina Exact screen").evaluate((v) => v.readyState >= 2 && v.videoWidth > 0), { timeout: 20_000 }).toBe(true)
  await shot(page, "live-no-camera")

  await submit(rina)
  const rita = await takeExam(browser, people["Rita Extra"], ["a", "b", "c", "d"])
  await submit(rita)
  const rani = await takeExam(browser, people["Rani Every"], ["a", "b", "c", "d", "e"])
  await submit(rani)

  // the review: the written answer is there (not "No answer"), and the marks follow the rule
  const mark = async (w, name) => {
    await page.goto(`/admin/results/${exam.id}/${w.attempt}`)
    const q = (title) => page.getByTestId("review-question").filter({ hasText: title })
    return { text: page.getByTestId("answer-text"), score: await q("Honesty multi").getByTestId("question-score").innerText(), name }
  }
  const a = await mark(rina)
  await expect(a.text).toHaveText(WRITTEN)
  expect(a.score).toBe("3 / 3")
  await shot(page, "review-written-answer")
  expect((await mark(rita)).score).toBe("2.75 / 3")  // all right and one wrong: 0.25 off
  expect((await mark(rani)).score).toBe("0 / 3")     // ticking everything does not win
  for (const w of [rina, rita, rani]) await w.ctx.close()
})
