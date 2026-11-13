import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// Write or change one question with AI, from the Question bank and inside the question editor. The AI is a fixed stand-in (tests/e2e_server.py): the words
// of the request decide what it answers (CODING, SQL, WRITTEN, BROKEN, REFUSE, SLOW, Check-me, "fifth", "harder", "marks"), or the real model when RUN_AI=1.
const figure = "e2e/fixtures/figure.png"
const box = (page) => page.getByTestId("ai-assist")
const ask = async (page, text, button = "Write question") => {
  await box(page).getByLabel("Tell the AI what you want").fill(text)
  await box(page).getByRole("button", { name: button }).click()
}
const loaded = (loc) => loc.evaluateAll((imgs) => imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0))
const bank = (api, title) => api.get(`/questions?q=${encodeURIComponent(title)}`)

test.skip(!!process.env.RUN_AI, "these use the fixed answers of the stand-in AI; the RUN_AI tests are at the end")

test("Create with AI from the bank: the form is filled, nothing is saved until Save, then it is in the bank", async ({ page, request }) => {
  await loginStaff(page)
  const api = await staffRequest(request)
  const before = (await bank(api, "Capital of Japan")).length
  await page.goto("/admin/questions")
  await page.getByRole("link", { name: "Create with AI" }).click()
  await expect(page).toHaveURL(/\/admin\/questions\/new\?ai=1/)
  await expect(box(page)).toContainText("Write a question with AI")
  await expect(box(page).getByRole("button", { name: "Write question" })).toBeDisabled()   // nothing asked yet
  await ask(page, "One easy question: the capital of Japan")

  await expect(box(page).getByTestId("ai-result")).toContainText("Wrote the question.")
  await expect(box(page).getByTestId("ai-warning")).toHaveCount(0)                          // the independent answer agrees
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Capital of Japan")
  await expect(page.getByLabel("Option 2", { exact: true })).toHaveValue("Tokyo")
  await expect(page.getByLabel("Option 2 is correct")).toBeChecked()
  await expect(page.getByLabel("Option 1 is correct")).not.toBeChecked()
  await expect(box(page)).toContainText("Change this question with AI")                      // the box now changes this question
  expect((await bank(api, "Capital of Japan")).length).toBe(before)                          // not saved yet
  await shot(page, "question-ai-created")

  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  await expect(page.getByRole("row").nth(1)).toContainText("Capital of Japan")             // at the top of the bank
  expect((await bank(api, "Capital of Japan")).length).toBe(before + 1)
})

test("a picture of a question: it is read, kept where the question needs it, and the box is cleared", async ({ page, request }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Choose a picture for the request").setInputFiles(figure)
  await expect(box(page).getByTestId("request-pictures").getByRole("img")).toHaveCount(1)
  await box(page).getByRole("button", { name: "Write question" }).click()                      // a picture alone is enough
  await expect(box(page).getByTestId("ai-result")).toBeVisible()
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("City from the picture")
  const own = page.getByTestId("question-pictures")
  await expect(own.getByRole("img")).toHaveCount(1)
  expect(await loaded(own.getByRole("img"))).toBe(true)
  await expect(box(page).getByTestId("request-pictures").getByRole("img")).toHaveCount(0)
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  const api = await staffRequest(request)
  const q = (await bank(api, "City from the picture"))[0]
  expect((await api.get(`/questions/${q.id}`)).body).toContain('<img src="data:image/png;base64,')
})

test("change the question with a follow-up, see what changed, and undo it", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "easy question about Japan")
  await expect(page.getByLabel("Option 4", { exact: true })).toBeVisible()
  await expect(page.getByLabel("Option 5", { exact: true })).toHaveCount(0)
  await ask(page, "make it harder and add a fifth option", "Change question")
  await expect(box(page).getByTestId("ai-result")).toContainText("Added a fifth option, Sapporo.")
  await expect(box(page).getByTestId("ai-result")).toContainText("Made the question harder.")
  await expect(page.getByLabel("Option 5", { exact: true })).toHaveValue("Sapporo")
  await expect(page.getByLabel("Option 2 is correct")).toBeChecked()                        // the answer stayed
  await expect(page.getByLabel("Question text")).toHaveValue(/Think carefully/)
  await expect(box(page).getByLabel("Tell the AI what you want")).toHaveValue("")           // ready for the next instruction
  await box(page).getByRole("button", { name: "Undo the last AI change" }).click()
  await expect(page.getByLabel("Option 5", { exact: true })).toHaveCount(0)
  await expect(page.getByLabel("Question text")).not.toHaveValue(/Think carefully/)
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Capital of Japan")
  await expect(box(page).getByRole("button", { name: "Undo the last AI change" })).toHaveCount(0)
})

test("a second AI opinion that disagrees is a visible warning, and the question is still there to read", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "Check-me please")
  await expect(box(page).getByTestId("ai-warning")).toContainText("it chose b, the key says a")
  await expect(page.getByLabel("Option 1 is correct")).toBeChecked()
  await shot(page, "question-ai-warning")
})

test("a question the platform refuses, or a request that is no question, says why and leaves the form alone", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "BROKEN question")
  await expect(box(page).getByTestId("ai-error")).toContainText("could not make a valid question")
  await expect(box(page).getByTestId("ai-error")).toContainText("correct answer 'z'")
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("")                   // nothing was filled
  await expect(box(page).getByLabel("Tell the AI what you want")).toHaveValue("BROKEN question")  // and the request is still there to change
  await ask(page, "an easy question")
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Capital of Japan")
  await expect(box(page).getByTestId("ai-error")).toHaveCount(0)
  await ask(page, "REFUSE this", "Change question")
  await expect(box(page).getByTestId("ai-error")).toHaveText("That is not a question.")
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Capital of Japan")   // the question was not touched
})

test("Cancel stops a slow request and nothing changes", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "SLOW please")
  await expect(box(page).getByRole("status")).toContainText("up to a minute")
  await expect(box(page).getByLabel("Tell the AI what you want")).toBeDisabled()
  await box(page).getByRole("button", { name: "Cancel" }).click()
  await expect(box(page).getByRole("button", { name: "Write question" })).toBeEnabled()
  await expect(box(page).getByTestId("ai-error")).toHaveCount(0)
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("")
})

test("an existing question is changed with AI from its edit page and saved", async ({ page, request }) => {
  await loginStaff(page)
  const api = await staffRequest(request)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "a question about Japan")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  const q = (await bank(api, "Capital of Japan"))[0]
  await page.goto(`/admin/questions/${q.id}`)
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Capital of Japan")
  await page.getByRole("button", { name: "Write or change this question with AI" }).click()
  await expect(box(page)).toContainText("Change this question with AI")
  await expect(box(page).getByLabel("Type of question to write")).toHaveCount(0)             // the type of an existing question stays
  await ask(page, "worth 3 marks", "Change question")
  await expect(page.getByLabel("Marks", { exact: true })).toHaveValue("3")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  const saved = await api.get(`/questions/${q.id}`)
  expect(saved.marks).toBe(3)
  expect(saved.version).toBe(q.version + 1)                                                   // the same question, changed (not a copy)
})

test("coding, SQL and written questions arrive in their own forms and save", async ({ page, request }) => {
  await loginStaff(page)
  const api = await staffRequest(request)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Type of question to write").click()
  await page.getByRole("option", { name: "Coding" }).click()
  await ask(page, "CODING: add two numbers")
  await expect(box(page).getByTestId("ai-warning")).toHaveCount(0)                           // a second solution gives the same outputs
  await expect(page.getByText("Test cases", { exact: true })).toBeVisible()
  await expect(page.getByTestId("case-row")).toHaveCount(4)
  await expect(page.getByLabel("Case 1 expected output")).toHaveValue(/5/)                   // computed by running the reference solution
  await page.getByRole("button", { name: "Check reference solution" }).click()
  await expect(page.getByText("Reference solution passes all 4 cases")).toBeVisible()
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  const code = (await bank(api, "Sum of two numbers"))[0]
  expect(code.type).toBe("coding")
  expect(code.validated).toBe(true)

  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "SQL: well paid employees")
  await expect(page.getByText("employees").first()).toBeVisible()
  await shot(page, "question-ai-sql")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  expect((await bank(api, "Well paid employees"))[0].validated).toBe(true)

  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "WRITTEN: primary key")
  await expect(box(page).getByTestId("ai-result")).toContainText("read it once")
  await expect(page.getByLabel("Model answer")).toHaveValue(/unique/)
})

test("the department decides which types the AI may write", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await page.getByLabel("Department", { exact: true }).click()
  await page.getByRole("option", { name: "HR", exact: true }).click()
  await box(page).getByLabel("Type of question to write").click()
  await expect(page.getByRole("option", { name: "Let the AI choose" })).toBeVisible()
  await expect(page.getByRole("option", { name: "Short answer" })).toBeVisible()
  await expect(page.getByRole("option", { name: "Coding" })).toHaveCount(0)
  await expect(page.getByRole("option", { name: "SQL" })).toHaveCount(0)
})

test("only people who may write questions see the button, and it fits a phone", async ({ page }) => {
  await loginStaff(page, "evaluator@globx.co.in")                                          // may read the bank, not write to it
  await page.goto("/admin/questions")
  await expect(page.getByRole("heading", { name: "Question bank" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Create with AI" })).toHaveCount(0)
  await page.context().clearCookies()
  await page.evaluate(() => localStorage.clear())
  await loginStaff(page)
  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto("/admin/questions/new?ai=1")
  await expect(box(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, "question-ai-phone")
})
