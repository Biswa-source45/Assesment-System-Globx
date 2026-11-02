import { expect, test } from "@playwright/test"
import { creds, login, loginStaff, shot } from "./helpers"

const BANK = /\/admin\/questions$/

test("wrong password is rejected, right one reaches the admin area", async ({ page }) => {
  await login(page, "recruiter@globx.co.in", "not-the-password")
  await expect(page.getByText("Invalid email or password")).toBeVisible()
  await login(page, "recruiter@globx.co.in", creds()["recruiter@globx.co.in"])
  await expect(page).toHaveURL(/\/admin/)
  await expect(page.getByRole("heading", { name: "Exams" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "Practice Test" })).toBeVisible()
  await shot(page, "admin-exams")
})

test("saving a new MCQ returns to the question bank with the question at the top; it can then be archived", async ({ page }) => {
  await loginStaff(page)
  await page.getByRole("link", { name: "Question bank" }).click()
  await expect(page.getByRole("heading", { name: "Question bank" })).toBeVisible()
  await shot(page, "bank-list")

  await page.getByLabel("Filter by type").click()
  await page.getByRole("option", { name: "Coding" }).click()
  await expect(page.getByRole("cell", { name: "Coding", exact: true }).first()).toBeVisible()
  await expect(page.getByRole("cell", { name: /MCQ/ })).toHaveCount(0)

  await page.getByRole("link", { name: "New question" }).click()
  await page.getByLabel("Title").fill("E2E: capital of France")
  await page.getByLabel("Question text").fill("Which city is the capital of France?")
  for (const [i, text] of ["Berlin", "Paris", "Madrid", "Rome"].entries()) await page.getByLabel(`Option ${i + 1}`, { exact: true }).fill(text)
  await page.getByRole("radio", { name: "Option 2 is correct" }).click()
  await shot(page, "bank-editor-mcq")
  await page.getByRole("button", { name: "Save question" }).click()

  await expect(page.getByText("Question created")).toBeVisible()
  await expect(page).toHaveURL(BANK)
  await expect(page.getByRole("row").nth(1)).toContainText("E2E: capital of France")  // newest first

  await page.getByLabel("Search questions").fill("E2E: capital")
  const row = page.getByRole("row").filter({ hasText: "E2E: capital of France" })
  page.once("dialog", (d) => d.accept())
  await row.getByRole("button", { name: "Archive" }).click()
  await expect(page.getByText("Archived")).toBeVisible()
  await expect(row).toHaveCount(0)
})

test("saving an MCQ with no correct answer shows the server's message and stays on the form", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await page.getByLabel("Title").fill("E2E: no answer")
  await page.getByLabel("Option 1", { exact: true }).fill("A")
  await page.getByLabel("Option 2", { exact: true }).fill("B")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("exactly one correct option")).toBeVisible()
  await expect(page).toHaveURL(/\/admin\/questions\/new/)
})

test("explained answer: create, find it at the top of the bank, reopen and edit it", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await page.getByLabel("Question type").click()
  await page.getByRole("option", { name: "Explained answer" }).click()
  await page.getByLabel("Title").fill("E2E: explain caching")
  await page.getByLabel("Question text").fill("Explain how a cache speeds up a web app.")
  await page.getByLabel("Model answer", { exact: true }).fill("Stores recent results in fast memory so repeated requests skip slow work.")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(BANK)
  await page.getByRole("row").nth(1).getByRole("link", { name: "E2E: explain caching" }).click()
  await expect(page.getByLabel("Model answer", { exact: true })).toHaveValue(/fast memory/)
  await page.getByLabel("Title").fill("E2E: explain caching (v2)")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("Question saved")).toBeVisible()
  await expect(page).toHaveURL(BANK)
  await expect(page.getByRole("row").nth(1)).toContainText("E2E: explain caching (v2)")
})

test("coding question: check and AI generation work before saving; save returns to the bank", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await page.getByLabel("Question type").click()
  await page.getByRole("option", { name: "Coding" }).click()
  await page.getByLabel("Title").fill("E2E: double it")
  await page.getByLabel("Question text").fill("Read an integer n and print 2n.")
  await page.getByLabel("Constraints").fill("0 <= n <= 1000000")
  await expect(page.getByRole("button", { name: "Generate with AI" })).toBeDisabled()  // needs a reference and a sample first
  await page.getByRole("textbox", { name: "Reference solution" }).fill("n = int(input())\nprint(2 * n)")
  await page.getByRole("button", { name: "Add case" }).click()
  await page.getByLabel("Case 1 input").fill("4\n")
  await page.getByLabel("Case 1 expected output").fill("8")
  await page.getByRole("button", { name: "Add case" }).click()
  await page.getByLabel("Case 2 input").fill("0\n")
  await page.getByLabel("Case 2 expected output").fill("7")  // deliberately wrong
  await expect(page.getByLabel("Case 2 visibility")).toContainText("Hidden")

  await page.getByRole("button", { name: "Check reference solution" }).click()  // no save needed
  await expect(page.getByText(/passes 1 of 2 cases/)).toBeVisible({ timeout: 30_000 })
  const rows = page.getByTestId("case-row")
  await expect(rows.nth(0)).toContainText("Success")
  await expect(rows.nth(1)).toContainText("Failed")
  await page.getByLabel("Case 2 expected output").fill("0")
  await page.getByRole("button", { name: "Check reference solution" }).click()
  await expect(page.getByText("Reference solution passes all 2 cases")).toBeVisible({ timeout: 30_000 })

  // calls the real OpenAI API (cents); run with RUN_AI=1
  if (process.env.RUN_AI) {
    await page.getByRole("button", { name: "Generate with AI" }).click()
    await expect(page.getByText(/cases added as hidden/)).toBeVisible({ timeout: 90_000 })
    expect(await rows.count()).toBeGreaterThan(4)
    await shot(page, "bank-editor-coding-ai")
  }
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(BANK)
  await expect(page.getByRole("row").nth(1)).toContainText("E2E: double it")
})
