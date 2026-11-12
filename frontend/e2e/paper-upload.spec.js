import fs from "node:fs"
import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// Upload a question paper: the three loading steps, the review (pictures, notes, the answer the AI chose, a broken question), import, cancel,
// bad files, pictures in the question editor (also pasted), and the candidate's screen. The AI step is a fixed answer (tests/e2e_server.py), or
// the real model when RUN_AI=1.
const dialog = (page) => page.getByRole("dialog")
// the Word paper is kept as base64 text (a .docx file must never be committed); it is a small aptitude paper with a graph and four picture options
const paper = { name: "question-paper.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from(fs.readFileSync("e2e/fixtures/question-paper.docx.b64", "utf8"), "base64") }
const figure = "e2e/fixtures/figure.png"

async function createExam(page, department, title) {
  await page.goto("/admin/exams/new")
  await page.getByLabel("Department", { exact: true }).click()
  await page.getByRole("option", { name: department, exact: true }).click()
  await page.getByLabel("Title", { exact: true }).fill(title)
  await page.getByLabel("Description").fill("Paper upload description for " + title)
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}\?tab=questions/)
}
const openUpload = async (page) => { await page.getByRole("button", { name: "Build with AI" }).click(); await expect(dialog(page).getByTestId("paper-upload")).toBeVisible() }
const choose = (page, file) => dialog(page).getByLabel("Question paper file").setInputFiles(file)
const loaded = (loc) => loc.evaluateAll((imgs) => imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0))

test("upload a Word paper: steps, review with pictures, the AI-chosen answer, a broken question left out, notes, then import", async ({ page, request }) => {
  test.skip(!!process.env.RUN_AI, "this one checks the fixed answer of the stand-in AI; RUN_AI has its own test below")
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Paper Exam")
  await openUpload(page)
  await expect(dialog(page).getByTestId("json-route")).not.toHaveAttribute("open", "")  // the copy-and-paste way is tucked away
  await choose(page, paper)

  const steps = dialog(page).getByTestId("paper-steps")
  await expect(steps).toContainText("Reading the file")
  await expect(dialog(page).getByTestId("paper-review")).toBeVisible({ timeout: 30_000 })
  await expect(steps.locator("[data-state=done]")).toHaveCount(3)
  await expect(steps).toContainText("Word file, 5 pictures found")
  await expect(steps).toContainText("Completed")

  const review = dialog(page).getByTestId("paper-review")
  await expect(dialog(page).getByTestId("paper-notes")).toContainText("chart on page 3")
  const rows = review.getByTestId("paper-question")
  await expect(rows).toHaveCount(4)
  await expect(review.locator("[data-ok=true]")).toHaveCount(3)
  await expect(review).toContainText("3 of 4 questions are ready. 3 will be added.")
  // the graph is attached to question 1; question 2's four options are pictures; the answer of question 2 was chosen by the AI
  expect(await loaded(rows.nth(0).locator("img"))).toBe(true)
  await expect(rows.nth(1).locator("li img")).toHaveCount(4)
  expect(await loaded(rows.nth(1).locator("li img"))).toBe(true)
  await expect(review.getByTestId("ai-answer")).toHaveCount(1)
  await expect(rows.nth(1).getByTestId("ai-answer")).toBeVisible()
  await expect(rows.nth(1).locator("li").nth(2).getByLabel("Correct answer")).toBeVisible()  // C is the key
  await expect(rows.nth(1).getByLabel("Correct answer")).toHaveCount(1)
  // the broken one says why, and cannot be added
  await expect(rows.nth(2).getByTestId("paper-problems")).toContainText("correct answer 'z' is not one of the options")
  await expect(rows.nth(2).getByLabel("Include question 3")).toBeDisabled()
  await expect(review.getByRole("button", { name: "Import 3 questions" })).toBeVisible()
  await shot(page, "paper-upload-review")

  // leave one out, then import: only the ticked ones arrive, in their sections, and nothing was saved before
  const api = await staffRequest(request)
  expect((await api.get("/questions?q=Capital%20of%20France")).length).toBe(0)
  await rows.nth(3).getByLabel("Include question 1").click()
  await expect(review.getByRole("button", { name: "Import 2 questions" })).toBeVisible()
  await review.getByRole("button", { name: "Import 2 questions" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByTestId("exam-section")).toHaveCount(1)
  await expect(page.getByTestId("exam-section").first().locator("input").first()).toHaveValue("Reasoning")
  await expect(page.getByTestId("exam-section").first()).toContainText("Speed from a graph")
  await expect(page.getByTestId("exam-totals")).toContainText("2 questions")
  expect((await api.get("/questions?q=Next%20figure")).length).toBe(1)
  expect((await api.get("/questions?q=Capital%20of%20France")).length).toBe(0)
  expect((await api.get("/questions?q=Broken%20question")).length).toBe(0)

  // the imported question keeps its option pictures when it is opened in the editor
  const q = (await api.get("/questions?q=Next%20figure"))[0]
  await page.goto(`/admin/questions/${q.id}`)
  await expect(page.getByRole("img", { name: "Picture of option 3" })).toBeVisible()
  expect(await loaded(page.locator("img[alt^='Picture of option']"))).toBe(true)
})

test("Cancel stops a slow upload cleanly; a bad file gets a plain reason; a good file then works", async ({ page }) => {
  test.skip(!!process.env.RUN_AI, "uses the stand-in AI")
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Paper Cancel")
  await openUpload(page)

  await choose(page, "e2e/fixtures/slow-paper.txt")        // the stand-in AI takes 8 seconds for this one
  const steps = dialog(page).getByTestId("paper-steps")
  await expect(steps.locator("[data-state=run]")).toContainText("Understanding the questions")
  await expect(steps).toContainText(/\d+ s \(usually 20 to 90 seconds\)/)
  await dialog(page).getByRole("button", { name: "Cancel" }).first().click()
  await expect(steps).toHaveCount(0)
  await expect(dialog(page).getByRole("button", { name: "Choose question paper" })).toBeVisible()
  await page.waitForTimeout(1500)
  await expect(dialog(page).getByTestId("paper-review")).toHaveCount(0)

  await choose(page, { name: "old.doc", mimeType: "application/msword", buffer: Buffer.from("x") })
  await expect(dialog(page).getByTestId("paper-error")).toContainText("Save as .docx")
  await expect(steps.locator("[data-state=fail]")).toContainText("Reading the file")
  await choose(page, { name: "empty.txt", mimeType: "text/plain", buffer: Buffer.alloc(0) })
  await expect(dialog(page).getByTestId("paper-error")).toContainText("The file is empty")

  await choose(page, "e2e/fixtures/plain-paper.txt")        // no pictures in this one: the picture ids the stand-in names do not exist, and the review says so
  await expect(dialog(page).getByTestId("paper-review")).toBeVisible({ timeout: 30_000 })
  await expect(dialog(page).getByTestId("paper-error")).toHaveCount(0)
  await expect(dialog(page).getByTestId("paper-notes")).toContainText("does not exist")
  await dialog(page).getByRole("button", { name: "Start again with another file" }).click()
  await expect(dialog(page).getByTestId("paper-review")).toHaveCount(0)
  await dialog(page).getByRole("button", { name: "Cancel" }).last().click()
  await expect(page.getByTestId("exam-section")).toHaveCount(0)                      // nothing was added
})

test("the dialog fits a phone", async ({ page }) => {
  test.skip(!!process.env.RUN_AI, "uses the stand-in AI")
  await page.setViewportSize({ width: 360, height: 740 })
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Paper Phone")
  await openUpload(page)
  await choose(page, paper)
  await expect(dialog(page).getByTestId("paper-review")).toBeVisible({ timeout: 30_000 })
  const wide = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth, document.querySelector("[role=dialog]").scrollWidth, document.querySelector("[role=dialog]").clientWidth])
  expect(wide[0]).toBeLessThanOrEqual(wide[1])
  expect(wide[2]).toBeLessThanOrEqual(wide[3])
  await shot(page, "paper-upload-phone")
})

test("pictures in the question editor: added, pasted, on an option; kept after saving and reopening", async ({ page, request }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await page.getByLabel("Title", { exact: true }).fill("E2E picture question")
  await page.getByLabel("Question text").fill("Which figure is this?")
  await page.getByLabel("Choose a picture for the question").setInputFiles(figure)
  await expect(page.getByRole("img", { name: "Picture 1 of the question" })).toBeVisible()

  // a screenshot pasted into the text box becomes a second picture
  const b64 = fs.readFileSync(figure).toString("base64")
  await page.getByLabel("Question text").evaluate((el, data) => {
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0))
    const dt = new DataTransfer()
    dt.items.add(new File([bytes], "screenshot.png", { type: "image/png" }))
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }))
  }, b64)
  await expect(page.getByRole("img", { name: "Picture 2 of the question" })).toBeVisible()
  await expect(page.getByLabel("Question text")).toHaveValue("Which figure is this?")  // no picture code in the text box

  await page.getByLabel("Option 1", { exact: true }).fill("")
  await page.getByLabel("Choose a picture for option 1").setInputFiles(figure)        // an option that is only a picture
  await expect(page.getByRole("img", { name: "Picture of option 1" })).toBeVisible()
  await page.getByLabel("Option 2", { exact: true }).fill("Plain text")
  await page.getByLabel("Option 1 is correct").click()
  await page.getByLabel("Option 3", { exact: true }).fill("Three")
  await page.getByRole("button", { name: "Remove picture 2" }).click()                // removing works
  await expect(page.getByRole("img", { name: "Picture 2 of the question" })).toHaveCount(0)
  await shot(page, "editor-pictures")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)

  const api = await staffRequest(request)
  const saved = (await api.get("/questions?q=E2E%20picture%20question"))[0]
  await page.goto(`/admin/questions/${saved.id}`)
  await expect(page.getByRole("img", { name: "Picture 1 of the question" })).toBeVisible()
  await expect(page.getByRole("img", { name: "Picture 2 of the question" })).toHaveCount(0)
  await expect(page.getByRole("img", { name: "Picture of option 1" })).toBeVisible()
  await expect(page.getByLabel("Question text")).toHaveValue("Which figure is this?")
  expect(await loaded(page.locator("main img, [data-testid=question-pictures] img, img[alt^='Picture of option']"))).toBe(true)
  const full = await api.get(`/questions/${saved.id}`)
  expect(full.body).toContain("data:image/")
  expect(full.config.options[0].image).toMatch(/^data:image\//)
  expect(full.config.options[0].correct).toBe(true)

  // a bad save is explained, not lost: an option with neither a words nor a picture
  await page.getByRole("img", { name: "Picture of option 1" }).waitFor()
  await page.getByRole("button", { name: "Remove picture of option 1" }).click()
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("Option 1 needs a text or a picture").or(page.getByText("Single-correct MCQ needs exactly one correct option"))).toBeVisible()
})

test("a candidate sees the question picture and the option pictures, and can answer by picking a picture", async ({ page, request }) => {
  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const src = "data:image/png;base64," + fs.readFileSync(figure).toString("base64")
  const exam = await api.post("/tests", { department_id: dept, title: "E2E Picture Exam", duration_min: 30, shuffle_options: false, settings: { proctoring: { enabled: false } } })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "Part A" })).sections[0]
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: "E2E picture q", body: `<p>Look at the figure.</p><p><img src="${src}" alt="Picture 1"></p>`, marks: 1,
    config: { options: [{ id: "a", text: "", image: src, correct: true }, { id: "b", text: "A word", correct: false }] } })
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: ["Picture Person"] })).participants[0]

  await page.goto("/login")
  await page.getByLabel("Username or email").fill(p.username)
  await page.getByLabel("Password", { exact: true }).fill(p.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.locator("div[data-slot=card]").filter({ hasText: "E2E Picture Exam" }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)

  await expect(page.getByText("Look at the figure.")).toBeVisible()
  expect(await loaded(page.locator(".q-html img"))).toBe(true)
  const option = page.getByRole("radio").first()
  await expect(page.getByRole("img", { name: "Answer picture" })).toBeVisible()
  expect(await loaded(page.getByRole("img", { name: "Answer picture" }))).toBe(true)
  await option.click()                                                         // choosing the picture option counts as an answer
  await expect(option).toBeChecked()
  await shot(page, "candidate-picture-question")
})

test("RUN_AI: the real model reads the Word paper and attaches its pictures", async ({ page }) => {
  test.skip(!process.env.RUN_AI, "calls the real OpenAI API (cents); run with RUN_AI=1")
  test.setTimeout(240_000)
  await loginStaff(page)
  await createExam(page, "Technical", "E2E Paper Real AI")
  await openUpload(page)
  await choose(page, paper)
  await expect(dialog(page).getByTestId("paper-review")).toBeVisible({ timeout: 200_000 })
  await expect(dialog(page).getByTestId("paper-question").first()).toBeVisible()
  expect(await dialog(page).getByTestId("paper-question").count()).toBeGreaterThanOrEqual(3)
  expect(await dialog(page).getByTestId("paper-question").locator("img").count()).toBeGreaterThanOrEqual(2)
  await dialog(page).getByTestId("paper-review").screenshot({ path: "test-results/screens/paper-upload-real-ai.png" })  // the whole review, not only what fits the window
})
