import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

const dialog = (page) => page.getByRole("dialog")

test("departments: the defaults are there; create, edit and delete work, each asking first; a department in use cannot go", async ({ page }) => {
  await loginStaff(page)
  await page.getByRole("link", { name: "Departments" }).click()
  const rows = page.getByTestId("department-row")
  for (const name of ["Technical", "HR", "Finance", "Operations", "General"]) await expect(rows.filter({ hasText: name }).first()).toBeVisible()
  await expect(rows.filter({ hasText: "Technical" }).first()).toContainText("Coding")  // only Technical offers coding and SQL
  await expect(rows.filter({ hasText: "HR" }).first()).not.toContainText("Coding")
  await shot(page, "departments")

  await page.getByRole("button", { name: "New department" }).click()
  await page.getByLabel("Name").fill("Legal E2E")
  await dialog(page).getByRole("checkbox", { name: "Short answer" }).click()  // not every type for this one
  await dialog(page).getByRole("button", { name: "Create department" }).click()
  const legal = rows.filter({ hasText: "Legal E2E" })
  await expect(legal).toBeVisible()
  await expect(legal).not.toContainText("Short answer")

  await page.getByRole("button", { name: "Edit Legal E2E" }).click()
  await page.getByLabel("Name").fill("Legal E2E team")
  await dialog(page).getByRole("button", { name: "Save department" }).click()
  await expect(rows.filter({ hasText: "Legal E2E team" })).toBeVisible()

  // a department that questions or exams use cannot be deleted; the server says why
  await page.getByRole("button", { name: "Delete Technical" }).click()
  await dialog(page).getByRole("button", { name: "Delete" }).click()
  await expect(page.getByText(/is used by \d+ questions and \d+ exams/)).toBeVisible()
  await expect(rows.filter({ hasText: "Technical" }).first()).toBeVisible()

  // deleting asks first, and Cancel really cancels
  await page.getByRole("button", { name: "Delete Legal E2E team" }).click()
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(rows.filter({ hasText: "Legal E2E team" })).toBeVisible()
  await page.getByRole("button", { name: "Delete Legal E2E team" }).click()
  await dialog(page).getByRole("button", { name: "Delete" }).click()
  await expect(rows.filter({ hasText: "Legal E2E team" })).toHaveCount(0)
})

test("question types follow the department, and the bank can be filtered by it", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions/new")
  await expect(page.getByLabel("Department", { exact: true })).toContainText("Technical")  // the first department is the default
  await page.getByLabel("Question type").click()
  await expect(page.getByRole("option", { name: "Coding" })).toBeVisible()
  await expect(page.getByRole("option", { name: "SQL", exact: true })).toBeVisible()
  await page.getByRole("option", { name: "Coding" }).click()

  await page.getByLabel("Department", { exact: true }).click()  // HR has no coding: the type switches to one it offers
  await page.getByRole("option", { name: "HR" }).click()
  await expect(page.getByLabel("Question type")).toContainText("MCQ (one answer)")
  await page.getByLabel("Question type").click()
  await expect(page.getByRole("option", { name: "Coding" })).toHaveCount(0)
  await expect(page.getByRole("option", { name: "SQL", exact: true })).toHaveCount(0)
  await page.keyboard.press("Escape")

  await page.getByLabel("Title").fill("E2E HR scenario")
  await page.getByLabel("Question text").fill("A colleague asks you to cover for them. What do you do?")
  for (const [i, text] of ["Say yes to everything", "Ask what is needed and agree what you can do", "Ignore the request", "Tell the manager"].entries()) await page.getByLabel(`Option ${i + 1}`, { exact: true }).fill(text)
  await page.getByRole("radio", { name: "Option 2 is correct" }).click()
  await page.getByRole("button", { name: "Save question" }).click()

  await expect(page).toHaveURL(/\/admin\/questions$/)
  await expect(page.getByRole("row").nth(1)).toContainText("E2E HR scenario")
  await expect(page.getByRole("row").nth(1)).toContainText("HR")
  await page.getByLabel("Filter by department").click()
  await page.getByRole("option", { name: "HR" }).click()
  await expect(page.getByRole("link", { name: "E2E HR scenario" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Static method hiding" })).toHaveCount(0)  // a technical question
  await shot(page, "bank-by-department")
})

test("the server refuses a coding question in a department that does not offer it", async ({ request }) => {
  const api = await staffRequest(request)
  const hr = (await api.get("/departments")).find((d) => d.name === "HR").id
  const r = await api.send("post", "/questions", { department_id: hr, type: "coding", title: "Not allowed", body: "<p>x</p>", marks: 10, config: { languages: ["python"] },
    cases: [{ visibility: "open", input: "2", expected: "4" }, { visibility: "hidden", input: "3", expected: "6" }] })  // otherwise valid: only the department is wrong
  expect(r.status()).toBe(422)
  expect(await r.text()).toContain("does not offer coding")
})
