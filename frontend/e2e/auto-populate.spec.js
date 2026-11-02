import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

const dialog = (page) => page.getByRole("dialog")

const mcq = (department_id, title, difficulty, skills = []) => ({
  department_id, type: "mcq_single", title, body: "<p>Pick A.</p>", difficulty, skills, marks: 1,
  config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] },
})

async function newExam(page, department, title) {
  await page.goto("/admin/exams/new")
  await page.getByLabel("Department", { exact: true }).click()
  await page.getByRole("option", { name: department, exact: true }).click()
  await page.getByLabel("Title", { exact: true }).fill(title)
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}\?tab=questions/)
  await page.getByLabel("New section title").fill("Part 1")
  await page.getByRole("button", { name: "Add section" }).click()
  await expect(page.getByTestId("exam-section")).toHaveCount(1)
}

async function ask(page, { easy = 0, medium = 0, hard = 0 }) {
  await page.getByLabel("Easy", { exact: true }).fill(String(easy))
  await page.getByLabel("Medium", { exact: true }).fill(String(medium))
  await page.getByLabel("Hard", { exact: true }).fill(String(hard))
}

test("auto populate: random questions from the exam's department, reviewed before adding, never twice, shortfall explained", async ({ page, request }) => {
  const api = await staffRequest(request)  // a department with exactly 6 known questions: 3 easy, 2 medium, 1 hard
  const dept = await api.post("/departments", { name: "E2E Pop Dept", question_types: ["mcq_single"] })
  for (const [title, level] of [["Pop A1", "easy"], ["Pop A2", "easy"], ["Pop A3", "easy"], ["Pop B1", "medium"], ["Pop B2", "medium"], ["Pop C1", "hard"]]) {
    await api.post("/questions", mcq(dept.id, title, level))
  }

  await loginStaff(page)
  await newExam(page, "E2E Pop Dept", "E2E Populate Exam")
  await page.getByRole("button", { name: "Auto populate" }).click()
  await expect(page.getByLabel("Department to pick from")).toContainText("E2E Pop Dept")  // starts with the exam's department
  expect((await dialog(page).boundingBox()).width).toBeGreaterThan(600)  // as wide as asked, not squeezed to the base dialog's width

  await ask(page, { easy: 2, medium: 1, hard: 1 })
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  const rows = page.getByTestId("pick-row")
  await expect(rows).toHaveCount(4)
  await expect(rows.filter({ hasText: "easy" })).toHaveCount(2)
  await expect(rows.filter({ hasText: "medium" })).toHaveCount(1)
  await expect(rows.filter({ hasText: "hard" })).toHaveCount(1)
  await shot(page, "auto-populate-pick")

  await dialog(page).getByRole("button", { name: /Leave out/ }).first().click()  // look at the pick, drop one...
  await expect(rows).toHaveCount(3)
  await dialog(page).getByRole("button", { name: "Pick again" }).click()          // ...or pick again
  await expect(rows).toHaveCount(4)
  await dialog(page).getByRole("button", { name: "Add 4 questions" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByTestId("exam-item")).toHaveCount(4)
  await expect(page.getByTestId("exam-totals")).toContainText("4 questions, 4 marks")

  // one easy question is left: asking for three explains the shortfall and offers what exists
  await page.getByRole("button", { name: "Auto populate" }).click()
  await ask(page, { easy: 3 })
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  await expect(page.getByTestId("pick-short")).toContainText("2 more easy")
  await expect(rows).toHaveCount(1)
  await dialog(page).getByRole("button", { name: "Add 1 questions" }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(5)

  // the manual picker starts with the exam's department, and can look wider
  await page.getByRole("button", { name: "Add questions" }).click()
  await expect(page.getByLabel("Department filter")).toContainText("E2E Pop Dept")
  await expect(dialog(page).getByText("already in this exam")).toHaveCount(5)
  await page.getByLabel("Department filter").click()
  await page.getByRole("option", { name: "All departments" }).click()
  await page.getByLabel("Search the bank").fill("Static method hiding")
  await expect(dialog(page).getByRole("checkbox", { name: /Static method hiding/ })).toBeVisible()
  await page.keyboard.press("Escape")

  // removing a question asks first
  await page.getByTestId("exam-item").first().getByRole("button").click()
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(5)
  await page.getByTestId("exam-item").first().getByRole("button").click()
  await dialog(page).getByRole("button", { name: "Remove", exact: true }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(4)

  // publishing asks first too, and Cancel leaves the exam as a draft
  await page.getByRole("button", { name: "Publish" }).click()
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(page.getByTestId("exam-status")).toHaveText("draft")
  await page.getByRole("button", { name: "Publish" }).click()
  await dialog(page).getByRole("button", { name: "Publish" }).click()
  await expect(page.getByTestId("exam-status")).toHaveText("published")
  await expect(page.getByRole("button", { name: "Auto populate" })).toHaveCount(0)  // a published exam is frozen
})

test("auto populate from the seeded Finance bank: exactly its five questions, and a hard question short", async ({ page }) => {
  await loginStaff(page)
  await newExam(page, "Finance", "E2E Finance Exam")
  await page.getByRole("button", { name: "Auto populate" }).click()
  await expect(page.getByLabel("Department to pick from")).toContainText("Finance")
  await ask(page, { easy: 2, medium: 2, hard: 1 })
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  const rows = page.getByTestId("pick-row")
  await expect(rows).toHaveCount(5)
  for (const title of ["Profit over a period", "Percentage of an amount", "Straight-line depreciation", "Current assets", "Compound interest"]) {
    await expect(rows.filter({ hasText: title })).toHaveCount(1)
  }
  await expect(page.getByTestId("pick-short")).toHaveCount(0)

  await ask(page, { easy: 2, medium: 2, hard: 2 })  // only one hard question exists in Finance; changing the request clears the old pick
  await expect(rows).toHaveCount(0)
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  await expect(page.getByTestId("pick-short")).toContainText("1 more hard")
  await expect(rows).toHaveCount(5)

  await page.getByLabel("Only questions tagged with (optional, comma separated)").fill("accounting")  // a tag filter narrows it
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  await expect(rows).toHaveCount(3)  // the three Finance questions tagged accounting
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(0)  // nothing is added until you say so
})

test("a tall dialog scrolls on a small screen, so its buttons stay reachable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 520 })
  await loginStaff(page)
  await newExam(page, "Finance", "E2E Small Screen Exam")
  await page.getByRole("button", { name: "Auto populate" }).click()
  await ask(page, { easy: 2, medium: 2, hard: 1 })
  await dialog(page).getByRole("button", { name: "Pick questions" }).click()
  await expect(page.getByTestId("pick-row")).toHaveCount(5)
  const add = dialog(page).getByRole("button", { name: "Add 5 questions" })
  await add.scrollIntoViewIfNeeded()
  const box = await add.boundingBox()
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual(520)  // inside the screen, not cut off below it
  await add.click()
  await expect(page.getByTestId("exam-item")).toHaveCount(5)
})
