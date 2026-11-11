import { expect, test } from "@playwright/test"
import { confirmDialog, loginStaff, shot, staffRequest } from "./helpers"

// Critical buttons ask first, in the app's own dialog; table actions have a visible colour and border.
test("signing out asks first: Cancel keeps the session, Sign out ends it", async ({ page }) => {
  await loginStaff(page)
  await page.getByRole("button", { name: "Sign out" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText("Sign out?")
  await dialog.getByRole("button", { name: "Cancel" }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page).toHaveURL(/\/admin/)  // still signed in
  await page.getByRole("button", { name: "Sign out" }).click()
  await confirmDialog(page, "Sign out")
  await expect(page).toHaveURL(/\/login/)
})

test("Edit and Archive in the Question bank have colour and a border", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/questions")
  const row = page.locator("tbody tr").first()
  const style = (name) => row.getByRole(name === "Edit" ? "link" : "button", { name }).evaluate((el) => { const c = getComputedStyle(el); return { w: c.borderTopWidth, border: c.borderTopColor, color: c.color, bg: c.backgroundColor } })
  for (const name of ["Edit", "Archive"]) {
    const s = await style(name)
    expect(s.w).not.toBe("0px")
    expect(s.border).not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/)
    expect(s.color).not.toBe("rgb(0, 0, 0)")
  }
  await shot(page, "bank-buttons")
})

test("Create logins and Calculate ask first; Cancel does nothing", async ({ page, request }) => {
  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title: "E2E Confirm", duration_min: 30, settings: { proctoring: { enabled: false } } })
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}`)
  await page.getByRole("tab", { name: "Participants" }).click()
  await page.getByLabel("Participant names").fill("Asha Rao\nVikram Das")
  await page.getByRole("button", { name: "Create logins" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog).toContainText("Create 2 logins?")
  await dialog.getByRole("button", { name: "Cancel" }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByTestId("credentials")).toHaveCount(0)  // nothing was made
  expect((await api.get(`/tests/${exam.id}/results`)).summary.assigned).toBe(0)
  await page.getByRole("button", { name: "Create logins" }).click()
  await confirmDialog(page, "Create")
  await expect(page.getByTestId("credentials").getByTestId("cred-username")).toHaveCount(2)
  expect((await api.get(`/tests/${exam.id}/results`)).summary.assigned).toBe(2)
})
