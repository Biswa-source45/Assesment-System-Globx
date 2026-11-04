import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest } from "./helpers"

// Exams are archived, never deleted: only the Super Admin archives, sees the Archived window and the archived exams' results, and can restore.
async function publishedExam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>Pick A.</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30 })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${t.id}/publish`)
  await api.post(`/tests/${t.id}/participants`, { names: ["Archived Student"] })
  return t
}

const row = (page, title) => page.locator("tbody tr").filter({ hasText: title })

test("the Super Admin archives an exam and restores it; its results stay readable; a recruiter never sees any of it", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const title = "E2E Archive Exam"
  await publishedExam(api, title)

  await loginStaff(page, "superadmin@globx.co.in")
  await page.goto("/admin/exams")
  await expect(row(page, title)).toBeVisible()
  await page.getByRole("button", { name: `Archive ${title}` }).click()
  await expect(page.getByRole("dialog")).toContainText("Nothing is deleted")
  await page.getByRole("dialog").getByRole("button", { name: "Archive", exact: true }).click()
  await expect(page.getByText("Exam archived")).toBeVisible()
  await expect(row(page, title)).toHaveCount(0)

  // the Archived window holds it, with Restore instead of Archive
  await page.getByRole("tab", { name: "Archived" }).click()
  await expect(row(page, title)).toBeVisible()
  await expect(row(page, title).getByRole("button", { name: "Restore" })).toBeVisible()
  await expect(row(page, title).getByRole("button", { name: /^Archive / })).toHaveCount(0)
  await shot(page, "archived-exams")

  // the student data is not hidden: the exam is in Results (marked Archived) and opens with its candidates
  await page.goto("/admin/results")
  await expect(row(page, title).getByTestId("archived-badge")).toBeVisible()
  await row(page, title).getByRole("link", { name: "Open" }).click()
  await expect(page.getByText("Archived Student")).toBeVisible()

  // a recruiter sees none of it: not in the list, no Archived window, no Archive button, not in Results, not by address
  const other = await candidateWindow(browser)
  await loginStaff(other.page, "recruiter@globx.co.in")
  await other.page.goto("/admin/exams")
  await expect(other.page.getByRole("heading", { name: "Exams" })).toBeVisible()
  await expect(other.page.getByRole("tab", { name: "Archived" })).toHaveCount(0)
  await expect(other.page.getByRole("button", { name: /^Archive / })).toHaveCount(0)
  await expect(row(other.page, title)).toHaveCount(0)
  await other.page.goto("/admin/results")
  await expect(other.page.getByRole("heading", { name: "Results" })).toBeVisible()
  await expect(row(other.page, title)).toHaveCount(0)
  await other.ctx.close()

  // restore: back in the list exactly as it was
  await page.goto("/admin/exams")
  await page.getByRole("tab", { name: "Archived" }).click()
  await row(page, title).getByRole("button", { name: "Restore" }).click()
  await expect(page.getByText("Exam restored")).toBeVisible()
  await expect(row(page, title)).toHaveCount(0)
  await page.getByRole("tab", { name: "Exams" }).click()
  await expect(row(page, title).getByText("published")).toBeVisible()
  await shot(page, "archive-restored")
})
