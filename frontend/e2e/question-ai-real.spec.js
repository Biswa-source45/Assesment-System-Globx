import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// The same screens with the REAL model (RUN_AI=1; a few cents per run). The answers are not fixed, so these check what must hold whatever the wording:
// the form is filled, the right answer is the one the request implies, a picture is read, a change touches only what was asked, and the platform's checks pass.
test.skip(!process.env.RUN_AI, "calls the real model: run with RUN_AI=1")
test.setTimeout(240_000)

const photo = "e2e/fixtures/question-photo.png"
const figure = "e2e/fixtures/figure.png"
const box = (page) => page.getByTestId("ai-assist")
const ask = async (page, text, button = "Write question") => {
  await box(page).getByLabel("Tell the AI what you want").fill(text)
  await box(page).getByRole("button", { name: button }).click()
  await expect(box(page).getByTestId("ai-result").or(box(page).getByTestId("ai-error"))).toBeVisible({ timeout: 180_000 })
  await expect(box(page).getByTestId("ai-error")).toHaveCount(0)
}
const correctText = async (page, n = 4) => {
  for (let i = 1; i <= n; i++) {
    if (await page.getByLabel(`Option ${i} is correct`).isChecked()) return page.getByLabel(`Option ${i}`, { exact: true }).inputValue()
  }
  return ""
}

test("real model: a prompt makes a question whose answer is the one asked for, then a follow-up changes only what was asked", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await ask(page, "An easy multiple choice question: what is 15 percent of 200? The options are 20, 25, 30 and 35.")
  await expect(page.getByLabel("Title", { exact: true })).not.toHaveValue("")
  expect(await correctText(page)).toBe("30")
  await expect(page.getByLabel("Option 4", { exact: true })).toHaveValue("35")
  await expect(box(page).getByTestId("ai-warning")).toHaveCount(0)
  await shot(page, "question-ai-real-prompt")

  const title = await page.getByLabel("Title", { exact: true }).inputValue()
  await ask(page, "Change the numbers: ask for 18 percent of 250. Options 35, 45, 55, 65. Keep everything else.", "Change question")
  expect(await correctText(page)).toBe("45")
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(title)                // untouched
  await expect(page.getByLabel("Question text")).toHaveValue(/18/)
  await shot(page, "question-ai-real-change")
})

test("real model: a picture of a typed question is read faithfully and its answer ticked, no picture kept; picture plus words changes it", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Choose a picture for the request").setInputFiles(photo)
  await box(page).getByRole("button", { name: "Write question" }).click()
  await expect(box(page).getByTestId("ai-result")).toBeVisible({ timeout: 180_000 })
  await expect(page.getByLabel("Question text")).toHaveValue(/Red Planet/)
  expect(await correctText(page)).toMatch(/Mars/)
  await expect(page.getByLabel("Option 1", { exact: true })).toHaveValue(/Venus/)
  await expect(page.getByLabel("Marks", { exact: true })).toHaveValue("2")                  // the "[2 marks]" in the picture
  await expect(page.getByTestId("question-pictures").getByRole("img")).toHaveCount(0)        // a photo of text is not kept
  await shot(page, "question-ai-real-photo")

  // picture + words: the same kind of question, but the words change it
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Choose a picture for the request").setInputFiles(photo)
  await ask(page, "Use this question but add a fifth option, Mercury, and make Jupiter the correct answer.")
  await expect(page.getByLabel("Option 5", { exact: true })).toHaveValue(/Mercury/)
  expect(await correctText(page, 5)).toMatch(/Jupiter/)
})

test("real model: a graph question keeps the graph", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Choose a picture for the request").setInputFiles(figure)
  await ask(page, "Write one multiple choice question about this figure. The figure must be shown in the question.")
  await expect(page.getByTestId("question-pictures").getByRole("img")).toHaveCount(1)
})

test("real model: a coding question and an SQL question are checked by the platform and save", async ({ page, request }) => {
  await loginStaff(page)
  const api = await staffRequest(request)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Type of question to write").click()
  await page.getByRole("option", { name: "Coding" }).click()
  await ask(page, "A coding question: read an integer n and print the sum of the numbers from 1 to n. Python.")
  expect(await page.getByTestId("case-row").count()).toBeGreaterThanOrEqual(2)
  await page.getByRole("button", { name: "Check reference solution" }).click()
  await expect(page.getByText(/Reference solution passes all \d+ cases/)).toBeVisible()
  await shot(page, "question-ai-real-coding")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  expect((await api.get("/questions?type=coding"))[0].validated).toBe(true)

  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Type of question to write").click()
  await page.getByRole("option", { name: "SQL" }).click()
  await ask(page, "An SQL question on a table employees(id, name, salary): return the names of employees who earn more than 50000, sorted by name.")
  await shot(page, "question-ai-real-sql")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  expect((await api.get("/questions?type=sql"))[0].validated).toBe(true)
})

test("real model: a request that is not about a question gets a plain refusal", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new?ai=1")
  await box(page).getByLabel("Tell the AI what you want").fill("What is the weather like in Pune today?")
  await box(page).getByRole("button", { name: "Write question" }).click()
  await expect(box(page).getByTestId("ai-error")).toBeVisible({ timeout: 180_000 })
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("")
})
