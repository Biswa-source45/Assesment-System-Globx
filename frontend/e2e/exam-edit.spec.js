import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest, startProctoredExam } from "./helpers"

const dialog = (page) => page.getByRole("dialog")

const mcq = (department_id, title, body, extra = {}) => ({
  department_id, type: "mcq_single", title, body: `<p>${body}</p>`, difficulty: "easy", marks: 1,
  config: { options: [{ id: "a", text: "Alpha", correct: true }, { id: "b", text: "Beta", correct: false }] }, ...extra,
})

// A draft exam with two MCQs, made through the API the way a script would.
async function makeExam(request, title, bodies) {
  const api = await staffRequest(request)
  const tech = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const qs = []
  for (const [i, body] of bodies.entries()) qs.push(await api.post("/questions", mcq(tech, `${title} Q${i + 1}`, body)))
  const exam = await api.post("/tests", { department_id: tech, title, duration_min: 30, shuffle_questions: false, shuffle_options: false })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "Part 1" })).sections[0]
  for (const q of qs) await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  return { api, exam, qs }
}

test("edit a question inside the exam, draft or published, without visiting the bank; the bank shows the same change", async ({ page, request }) => {
  const { api, exam, qs } = await makeExam(request, "E2E Edit In Exam", ["Original one", "Original two"])
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=questions`)
  const rows = page.getByTestId("exam-item")
  await expect(rows).toHaveCount(2)

  // closing the panel without saving changes nothing
  await page.getByRole("button", { name: "Edit E2E Edit In Exam Q1" }).click()
  await expect(dialog(page).getByRole("heading", { name: "Edit question" })).toBeVisible()
  await expect(dialog(page).getByLabel("Title")).toHaveValue("E2E Edit In Exam Q1")
  await expect(dialog(page).getByLabel("Question text")).toHaveValue("Original one")
  await expect(dialog(page)).toContainText("also applies in the question bank")
  await dialog(page).getByLabel("Title").fill("Never saved")
  await page.keyboard.press("Escape")
  await expect(dialog(page)).toHaveCount(0)
  await expect(rows.first()).toContainText("E2E Edit In Exam Q1")

  // change title, wording, marks and add an option; the list, the totals and the bank follow
  await page.getByRole("button", { name: "Edit E2E Edit In Exam Q1" }).click()
  await dialog(page).getByLabel("Title").fill("E2E Edit In Exam Q1 reworded")
  await dialog(page).getByLabel("Question text").fill("Reworded one")
  await dialog(page).getByLabel("Marks", { exact: true }).fill("3")
  await dialog(page).getByRole("button", { name: "Add option" }).click()
  await dialog(page).getByLabel("Option 3", { exact: true }).fill("Gamma")
  await shot(page, "exam-edit-panel")
  await dialog(page).getByRole("button", { name: "Save question" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(rows.first()).toContainText("E2E Edit In Exam Q1 reworded")
  await expect(rows.first()).toContainText("3 marks")
  await expect(page.getByTestId("exam-totals")).toContainText("2 questions, 4 marks")
  const inBank = await api.get(`/questions/${qs[0].id}`)
  expect(inBank.title).toBe("E2E Edit In Exam Q1 reworded")
  expect(inBank.config.options.map((o) => o.text)).toEqual(["Alpha", "Beta", "Gamma"])
  expect(inBank.group_id ?? null).toBeNull()

  // a published exam is frozen for sections and questions, but a question can still be corrected, and the panel says who sees it
  await page.getByRole("button", { name: "Publish" }).click()
  await dialog(page).getByRole("button", { name: "Publish" }).click()
  await expect(page.getByTestId("exam-status")).toHaveText("published")
  await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0)
  await page.getByRole("button", { name: "Edit E2E Edit In Exam Q2" }).click()
  await expect(dialog(page)).toContainText("This exam is published")
  await dialog(page).getByLabel("Question text").fill("Corrected two")
  await dialog(page).getByRole("button", { name: "Save question" }).click()
  await expect(dialog(page)).toHaveCount(0)
  expect((await api.get(`/questions/${qs[1].id}`)).body).toContain("Corrected two")
})

test("a change made while candidates are in the exam reaches their screen, and their answers stay", async ({ page, browser, request }) => {
  const { api, exam, qs } = await makeExam(request, "E2E Live Edit", ["Original wording", "Second question"])
  await api.post(`/tests/${exam.id}/publish`)
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: ["Live Edit Taker"] })).participants[0]
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, p.username, "E2E Live Edit", p.password)
  await expect(cand.getByText("Original wording")).toBeVisible()
  await cand.getByText("Alpha", { exact: true }).click()
  await expect(cand.getByRole("radio", { name: "Alpha" })).toBeChecked()

  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=questions`)
  await page.getByRole("button", { name: "Edit E2E Live Edit Q1" }).click()
  await expect(dialog(page)).toContainText("1 candidate(s) are taking this exam right now")
  await shot(page, "exam-edit-live-warning")
  await dialog(page).getByLabel("Question text").fill("Changed wording")
  await dialog(page).getByRole("button", { name: "Add option" }).click()
  await dialog(page).getByLabel("Option 3", { exact: true }).fill("Gamma")
  await dialog(page).getByLabel("Marks", { exact: true }).fill("4")
  await dialog(page).getByRole("button", { name: "Save question" }).click()
  await expect(dialog(page)).toHaveCount(0)

  // the exam page checks the server every 15 seconds
  await expect(cand.getByText("Changed wording")).toBeVisible({ timeout: 30_000 })
  await expect(cand.getByText("Original wording")).toHaveCount(0)
  await expect(cand.getByText("Gamma", { exact: true })).toBeVisible()
  await expect(cand.getByText("The examiner updated")).toBeVisible()
  await expect(cand.getByRole("radio", { name: "Alpha" })).toBeChecked()  // the answer given before the change is kept
  await expect(cand.getByText("4 marks").first()).toBeVisible()
  await shot(cand, "exam-edit-candidate-updated")
  expect((await api.get(`/questions/${qs[0].id}`)).marks).toBe(4)
  await ctx.close()
})

test("saving a question of a linked set from the bank keeps it in its set", async ({ page, request }) => {
  const api = await staffRequest(request)
  const group = (await api.get("/groups")).find((g) => g.questions.length)
  const q = group.questions[0]
  await loginStaff(page)
  await page.goto(`/admin/questions/${q.id}`)
  await expect(page.getByLabel("Title")).toHaveValue(q.title)
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  expect((await api.get(`/questions/${q.id}`)).group_id).toBe(group.id)  // it used to be detached by the editor
})
