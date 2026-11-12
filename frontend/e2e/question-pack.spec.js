import { expect, test } from "@playwright/test"
import { loginStaff, shot } from "./helpers"

const dialog = (page) => page.getByRole("dialog")

// the dialog opens on the paper upload; the copy-and-paste way (prompt, JSON file) is inside a closed section
async function openAi(page) {
  await page.getByRole("button", { name: "Build with AI" }).click()
  await dialog(page).getByText("Or make the question file yourself with ChatGPT or Claude").click()
}

async function createExam(page, department, title) {
  await page.goto("/admin/exams/new")
  await page.getByLabel("Department", { exact: true }).click()
  await page.getByRole("option", { name: department, exact: true }).click()
  await page.getByLabel("Title", { exact: true }).fill(title)
  await page.getByLabel("Description").fill("Pack description for " + title)
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}\?tab=questions/)
}

const mcq = (n, extra = {}) => ({ type: "mcq_single", title: `E2E pack MCQ ${n}`, statement: "Pick B.", options: ["A", "B", "C"], correct: ["b"], ...extra })
const coding = {
  type: "coding", title: "E2E pack double it", statement: "Read n and print 2n.", marks: 10,
  reference: { language: "python", source: "print(2 * int(input()))" },
  test_cases: [{ input: "2", visibility: "open" }, { input: "21", visibility: "hidden" }],
}
const sql = {
  type: "sql", title: "E2E pack names", statement: "List names alphabetically.", marks: 10, schema: "CREATE TABLE t (name TEXT);",
  reference_sql: "SELECT name FROM t ORDER BY name",
  datasets: [{ data: "INSERT INTO t VALUES ('b'), ('a');", visibility: "open" }, { data: "INSERT INTO t VALUES ('z');", visibility: "hidden" }],
}
const file = (content, name = "questions.json") => ({ name, mimeType: "application/json", buffer: Buffer.from(typeof content === "string" ? content : JSON.stringify(content)) })

test("build an exam with AI: prompt with the exam's details, upload, review, import, publish", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Pack Exam")
  await openAi(page)
  expect((await dialog(page).boundingBox()).width).toBeGreaterThan(700)  // the dialog is as wide as asked (a plain max-w class lost to the base dialog's sm:max-w-sm)

  // step 1: the prompt carries the exam's details and exactly the counts asked for
  await dialog(page).getByLabel("MCQ (one answer)", { exact: true }).fill("3")
  await dialog(page).getByLabel("Coding", { exact: true }).fill("1")
  await dialog(page).getByLabel("SQL", { exact: true }).fill("1")
  await dialog(page).getByRole("button", { name: "Create prompt" }).click()
  const prompt = dialog(page).getByLabel("AI prompt")
  for (const part of ["Technical", "E2E Pack Exam", "Pack description for E2E Pack Exam", "60 minutes", "3 x multiple choice", "1 x coding", "1 x SQL", "5 in total", "globx-exam-questions/1"]) {
    await expect(prompt).toHaveValue(new RegExp(part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
  }
  await expect(prompt).not.toHaveValue(/"type": "short"/)
  await dialog(page).getByRole("button", { name: "Copy prompt" }).click()
  await expect(page.getByText("Prompt copied")).toBeVisible()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied.replace(/\r\n/g, "\n")).toBe(await prompt.inputValue())  // Windows clipboards use CRLF line ends
  await dialog(page).getByLabel("SQL", { exact: true }).fill("2")  // changing a count clears the old prompt
  await expect(dialog(page).getByLabel("AI prompt")).toHaveCount(0)

  // step 2: the AI usually wraps the JSON in a sentence and a code fence; that is fine
  const pack = { format: "globx-exam-questions/1", sections: [
    { title: "Part A: Multiple choice", timer_min: 15, questions: [mcq(1), mcq(2)] },
    { title: "Part B: Coding", questions: [coding] }, { title: "Part C: SQL", questions: [sql] },
  ] }
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file("Here is your file:\n```json\n" + JSON.stringify(pack, null, 2) + "\n```\nHope it helps!"))
  const preview = dialog(page).getByTestId("pack-preview")
  await expect(preview).toContainText("4 questions, 22 marks, in 3 sections")
  await expect(dialog(page).getByTestId("pack-section")).toHaveCount(3)
  await expect(dialog(page).getByTestId("pack-section").first()).toContainText("(15 min)")
  await shot(page, "question-pack-preview")

  await expect(page.getByTestId("exam-section")).toHaveCount(0)  // nothing is added until Import
  await dialog(page).getByRole("button", { name: "Import 4 questions" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByTestId("exam-section")).toHaveCount(3)
  await expect(page.getByTestId("exam-item")).toHaveCount(4)
  await expect(page.getByTestId("exam-totals")).toContainText("4 questions, 22 marks")
  await expect(page.getByTestId("exam-section").nth(1)).not.toContainText("Not validated")  // the server ran the solution: coding and SQL are publishable
  await shot(page, "question-pack-imported")

  await page.getByRole("button", { name: "Publish" }).click()
  await dialog(page).getByRole("button", { name: "Publish" }).click()
  await expect(page.getByTestId("exam-status")).toHaveText("published")
  await expect(page.getByRole("button", { name: "Build with AI" })).toHaveCount(0)  // a published exam is frozen
})

test("a file with mistakes lists every one, and adds nothing, not even the good questions", async ({ page }) => {
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Pack Mistakes")
  await openAi(page)
  const bad = { sections: [{ title: "Mixed", questions: [
    mcq(1, { title: "E2E pack fine one" }), mcq(2, { title: "E2E pack wrong letter", correct: ["f"] }),
    { ...coding, title: "E2E pack broken solution", reference: { language: "python", source: "print(1 / 0)" } },
  ] }] }
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file(bad))
  const errors = dialog(page).getByTestId("pack-errors")
  await expect(errors).toContainText("2 problem(s) found. Nothing was added")
  await expect(errors).toContainText("Section 1, question 2 (E2E pack wrong letter): correct answer 'f' is not one of the options")
  await expect(errors).toContainText("Section 1, question 3 (E2E pack broken solution): the reference solution fails on 2 of 2 test cases")
  await expect(dialog(page).getByRole("button", { name: /^Import/ })).toHaveCount(0)
  await shot(page, "question-pack-errors")

  // a corrected file goes through
  const fixed = { sections: [{ title: "Mixed", questions: [mcq(1, { title: "E2E pack fine one" }), mcq(2, { title: "E2E pack right letter" }), coding] }] }
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file(fixed))
  await expect(dialog(page).getByTestId("pack-errors")).toHaveCount(0)
  await expect(dialog(page).getByTestId("pack-preview")).toContainText("3 questions, 12 marks")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()  // Cancel really cancels
  await expect(page.getByTestId("exam-section")).toHaveCount(0)
  await expect(page.getByTestId("exam-totals")).toContainText("0 questions")
})

test("files that are not JSON are explained in plain words", async ({ page }) => {
  await loginStaff(page)
  await createExam(page, "General", "E2E Pack Not JSON")
  await openAi(page)
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file("Sorry, I cannot help with that.", "reply.txt"))
  await expect(dialog(page).getByTestId("pack-file-error")).toContainText("does not contain a JSON document")
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file('{"sections": [ {"title": "A", "questions": [], } ]}'))  // the trailing comma is the kind of slip an AI makes
  await expect(dialog(page).getByTestId("pack-file-error")).toContainText("not valid JSON")
  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file({ sections: [] }))
  await expect(dialog(page).getByTestId("pack-errors")).toContainText("at least one section")
})

test("the prompt and the file follow the exam's department: HR has no coding", async ({ page }) => {
  await loginStaff(page)
  await createExam(page, "HR", "E2E Pack HR Exam")
  await openAi(page)
  await expect(dialog(page).getByLabel("MCQ (one answer)", { exact: true })).toBeVisible()
  await expect(dialog(page).getByLabel("Coding", { exact: true })).toHaveCount(0)
  await expect(dialog(page).getByLabel("SQL", { exact: true })).toHaveCount(0)
  await dialog(page).getByRole("button", { name: "Create prompt" }).click()
  await expect(dialog(page).getByLabel("AI prompt")).toHaveValue(/Department: HR/)
  await expect(dialog(page).getByLabel("AI prompt")).not.toHaveValue(/"type": "coding"/)

  await dialog(page).getByLabel("Questions JSON file").setInputFiles(file({ sections: [{ title: "Tech", questions: [coding] }] }))
  await expect(dialog(page).getByTestId("pack-errors")).toContainText("does not offer coding")
})

test("the AI's answer can be pasted as text instead of uploaded: checked, previewed and imported the same way", async ({ page }) => {
  await loginStaff(page)
  await createExam(page, "General", "E2E Pack Paste Exam")
  await openAi(page)
  const paste = dialog(page).getByLabel("Pasted JSON")
  const check = dialog(page).getByRole("button", { name: "Check pasted JSON" })
  await expect(check).toBeDisabled()  // nothing pasted yet

  await paste.fill("Sure! I cannot give a file, sorry.")
  await check.click()
  await expect(dialog(page).getByTestId("pack-file-error")).toContainText("does not contain a JSON document")

  const pack = { sections: [{ title: "Pasted part", questions: [mcq(1, { title: "E2E pasted one" }), { type: "short", title: "E2E pasted short", statement: "Say hi.", model_answer: "Hi." }] }] }
  await paste.fill("Here is the exam:\n```json\n" + JSON.stringify(pack, null, 2) + "\n```")  // a chat reply, copied as it is
  await check.click()
  await expect(dialog(page).getByTestId("pack-file-error")).toHaveCount(0)
  await expect(dialog(page).getByTestId("pack-preview")).toContainText("2 questions, 3 marks, in 1 sections")
  await shot(page, "question-pack-paste")
  await dialog(page).getByRole("button", { name: "Import 2 questions" }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(2)
  await expect(page.getByTestId("exam-totals")).toContainText("2 questions, 3 marks")
})
