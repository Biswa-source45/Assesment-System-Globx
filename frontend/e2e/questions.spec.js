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

async function setType(page, label, name) {
  await page.getByLabel(label, { exact: true }).click()
  await page.getByRole("option", { name, exact: true }).click()
}

test("SQL question: tables and datasets are grids, the expected output is computed, saved and reopened", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await setType(page, "Question type", "SQL")
  await page.getByLabel("Title").fill("E2E: well paid staff")
  await page.getByLabel("Question text").fill("Return the names of staff earning more than 50000, sorted by name.")

  // the table, defined with fields and dropdowns: no CREATE TABLE
  await page.getByRole("button", { name: "Add table" }).click()
  await page.getByLabel("Table 1 name", { exact: true }).fill("staff")
  await page.getByLabel("Table 1 column 1 name", { exact: true }).fill("id")
  await setType(page, "Table 1 column 1 type", "INTEGER")
  await page.getByRole("button", { name: "Add column" }).click()
  await page.getByLabel("Table 1 column 2 name", { exact: true }).fill("name")
  await page.getByRole("button", { name: "Add column" }).click()
  await page.getByLabel("Table 1 column 3 name", { exact: true }).fill("salary")
  await setType(page, "Table 1 column 3 type", "INTEGER")

  // dataset 1 (sample): rows typed into a grid: no INSERT
  await page.getByRole("button", { name: "Add dataset" }).click()
  const rows1 = [["1", "Ben", "60000"], ["2", "Ann", "70000"], ["3", "Cy", "10000"]]
  for (const [i, row] of rows1.entries()) {
    await page.getByRole("button", { name: "Add row to staff" }).first().click()
    for (const [col, v] of ["id", "name", "salary"].entries()) await page.getByLabel(`Dataset 1 staff row ${i + 1} ${["id", "name", "salary"][col]}`, { exact: true }).fill(row[col])
  }
  // dataset 2 (hidden): one row
  await page.getByRole("button", { name: "Add dataset" }).click()
  await expect(page.getByLabel("Dataset 2 visibility", { exact: true })).toContainText("Hidden")
  await page.getByRole("button", { name: "Add row to staff" }).nth(1).click()
  for (const [col, v] of ["1", "Zed", "99000"].entries()) await page.getByLabel(`Dataset 2 staff row 1 ${["id", "name", "salary"][col]}`, { exact: true }).fill(v)

  await page.getByLabel("Solution query", { exact: true }).fill("SELECT name FROM staff WHERE salary > 50000 ORDER BY name")
  await page.getByRole("button", { name: /Run solution query/ }).click()
  const ds = page.getByTestId("sql-dataset")
  const out = (i) => ds.nth(i).locator("td[data-slot=table-cell]")  // cells of the expected-output table only, not the input grid
  await expect(out(0).filter({ hasText: "Ann" })).toBeVisible()  // expected output as a table
  await expect(out(0).filter({ hasText: "Ben" })).toBeVisible()
  await expect(out(0)).toHaveCount(2)                                        // Ann and Ben only: Cy earns too little
  await expect(out(1).filter({ hasText: "Zed" })).toBeVisible()
  await shot(page, "bank-editor-sql")

  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page).toHaveURL(BANK)
  const top = page.getByRole("row").nth(1)
  await expect(top).toContainText("E2E: well paid staff")
  await expect(top).toContainText("SQL")

  await top.getByRole("link", { name: "E2E: well paid staff" }).click()  // reopen: everything comes back as tables
  await expect(page.getByLabel("Table 1 name", { exact: true })).toHaveValue("staff")
  await expect(page.getByLabel("Table 1 column 3 type", { exact: true })).toContainText("INTEGER")
  await expect(page.getByLabel("Dataset 1 staff row 2 name", { exact: true })).toHaveValue("Ann")
  await expect(page.getByLabel("Dataset 2 visibility", { exact: true })).toContainText("Hidden")
  await expect(page.getByTestId("sql-dataset").nth(0).locator("td[data-slot=table-cell]").filter({ hasText: "Ben" })).toBeVisible()  // stored expected output shows without a rerun
})

test("SQL question: bad table names and a broken solution query are reported", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await setType(page, "Question type", "SQL")
  await page.getByLabel("Title").fill("E2E: bad sql")
  await page.getByRole("button", { name: "Add table" }).click()
  await page.getByLabel("Table 1 name", { exact: true }).fill("my table")
  await page.getByLabel("Table 1 column 1 name", { exact: true }).fill("a")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText(/Table name "my table" is not valid/)).toBeVisible()

  await page.getByLabel("Table 1 name", { exact: true }).fill("t")
  await page.getByRole("button", { name: "Add dataset" }).click()
  await page.getByRole("button", { name: "Add dataset" }).click()
  await page.getByRole("button", { name: "Add row to t" }).first().click()
  await page.getByLabel("Dataset 1 t row 1 a", { exact: true }).fill("x")
  await page.getByLabel("Solution query", { exact: true }).fill("SELECT nope FROM t")
  await page.getByRole("button", { name: /Run solution query/ }).click()
  await expect(page.getByTestId("sql-dataset").first().getByText(/no such column/i)).toBeVisible()
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText(/Dataset 1:/)).toBeVisible()
  await expect(page).toHaveURL(/\/admin\/questions\/new/)
})

test("the seeded SQL question opens as tables and saves unchanged", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions")
  await page.getByLabel("Filter by type").click()
  await page.getByRole("option", { name: "SQL", exact: true }).click()
  await page.getByRole("link", { name: "Top customers by revenue (2025)" }).click()
  await expect(page.getByLabel("Table 1 name", { exact: true })).toHaveValue("customers")
  await expect(page.getByLabel("Table 2 name", { exact: true })).toHaveValue("orders")
  await expect(page.getByTestId("sql-dataset")).toHaveCount(6)
  await expect(page.getByLabel("Solution query", { exact: true })).toHaveValue(/GROUP BY/)
  await shot(page, "bank-editor-sql-seeded")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("Question saved")).toBeVisible()
  await expect(page).toHaveURL(BANK)
})
