import { expect, test } from "@playwright/test"
import { BASE_URL, creds, login, loginStaff, shot, staffRequest } from "./helpers"

const dialog = (page) => page.getByRole("dialog")
const ORG = "orgadmin@globx.co.in"
const nav = (page, name) => page.locator("[data-sidebar=sidebar]").getByText(name, { exact: true })
const tryLogin = (request, email, password) => request.post("/api/v1/auth/login", { data: { email, password } })

test("user management: add, edit roles, change password, disable, unlock; each change takes effect for real", async ({ page, browser, request }) => {
  await loginStaff(page, ORG)
  await nav(page, "Users").click()
  await expect(page).toHaveURL(/\/admin\/users$/)
  const rows = page.getByTestId("user-row")
  for (const who of ["Super Admin", "Org Admin", "Priya Recruiter", "Tapas Test Creator", "Lipsa Evaluator"]) await expect(rows.filter({ hasText: new RegExp("^" + who) })).toHaveCount(1)  // the name starts the row (a Super Admin also carries the Org Admin role)
  await expect(page.getByRole("tab", { name: /^Staff \(\d+\)$/ })).toBeVisible()
  await expect(page.getByRole("tab", { name: /^Candidates \(\d+\)$/ })).toBeVisible()

  // the person is made with a generated password; an Org Admin cannot hand out Super Admin
  await page.getByRole("button", { name: "Add user" }).click()
  await expect(dialog(page).getByRole("checkbox", { name: "Org Admin" })).toBeVisible()
  await expect(dialog(page).getByRole("checkbox", { name: "Super Admin" })).toHaveCount(0)
  await dialog(page).getByLabel("Name").fill("E2E Staff Person")
  await dialog(page).getByLabel("Email").fill("e2e.staff@globx.co.in")
  await expect(dialog(page).getByRole("button", { name: "Create user" })).toBeDisabled()  // a role is needed
  await dialog(page).getByRole("checkbox", { name: "Recruiter" }).click()
  await dialog(page).getByRole("button", { name: "Generate" }).click()
  const first = await dialog(page).getByLabel("First password").inputValue()
  expect(first).toMatch(/^(?=.*[A-Za-z])(?=.*\d).{12}$/)
  await shot(page, "users-add")
  await dialog(page).getByRole("button", { name: "Create user" }).click()
  const row = rows.filter({ hasText: "E2E Staff Person" })
  await expect(row).toContainText("Recruiter")
  await expect(row).toContainText("Never")
  expect((await tryLogin(request, "e2e.staff@globx.co.in", first)).status()).toBe(200)

  // what they see follows their role: a recruiter has no Users and no Question bank
  const rec = await browser.newContext({ baseURL: BASE_URL })
  const recPage = await rec.newPage()
  await login(recPage, "e2e.staff@globx.co.in", first)
  await expect(nav(recPage, "Live monitor")).toBeVisible()
  await expect(nav(recPage, "Users")).toHaveCount(0)
  await expect(nav(recPage, "Question bank")).toHaveCount(0)

  // roles change; the same email is refused for someone else; the list can be searched and filtered
  await page.getByRole("button", { name: "Edit E2E Staff Person" }).click()
  await dialog(page).getByRole("checkbox", { name: "Recruiter" }).click()
  await dialog(page).getByRole("checkbox", { name: "Evaluator" }).click()
  await dialog(page).getByLabel("Name").fill("E2E Staff Renamed")
  await dialog(page).getByRole("button", { name: "Save user" }).click()
  const renamed = rows.filter({ hasText: "E2E Staff Renamed" })
  await expect(renamed).toContainText("Evaluator")
  await expect(renamed).not.toContainText("Recruiter")
  await page.getByRole("button", { name: "Edit E2E Staff Renamed" }).click()
  await dialog(page).getByLabel("Email").fill("recruiter@globx.co.in")
  await dialog(page).getByRole("button", { name: "Save user" }).click()
  await expect(dialog(page)).toContainText("already exists")  // the server's reason, in the dialog
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await page.getByLabel("Search users").fill("e2e staff")
  await expect(rows).toHaveCount(1)
  await page.getByLabel("Search users").fill("")
  await page.getByLabel("Filter by role").click()
  await page.getByRole("option", { name: "Evaluator" }).click()
  await expect(rows.filter({ hasText: "Lipsa Evaluator" })).toHaveCount(1)
  await expect(rows.filter({ hasText: "Priya Recruiter" })).toHaveCount(0)
  await page.getByLabel("Filter by role").click()
  await page.getByRole("option", { name: "All roles" }).click()

  // a new password: the old one stops, the open session ends, the new one works
  await page.getByRole("button", { name: "Change password for E2E Staff Renamed" }).click()
  await dialog(page).getByRole("button", { name: "Generate" }).click()
  const second = await dialog(page).getByLabel("New password").inputValue()
  await dialog(page).getByRole("button", { name: "Set password" }).click()
  await expect(dialog(page)).toHaveCount(0)
  expect((await tryLogin(request, "e2e.staff@globx.co.in", first)).status()).toBe(401)
  expect((await tryLogin(request, "e2e.staff@globx.co.in", second)).status()).toBe(200)
  await page.getByRole("button", { name: "Change password for E2E Staff Renamed" }).click()
  await dialog(page).getByLabel("New password").fill("short")
  await dialog(page).getByRole("button", { name: "Set password" }).click()
  await expect(dialog(page)).toContainText("at least 8 characters")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()

  // disabling stops sign-in at once; the person who is signed in is out on their next click
  await page.getByRole("button", { name: "Edit E2E Staff Renamed" }).click()
  await dialog(page).getByLabel("Status").click()
  await page.getByRole("option", { name: /^Disabled/ }).click()
  await dialog(page).getByRole("button", { name: "Save user" }).click()
  await expect(renamed).toContainText("Disabled")
  expect((await tryLogin(request, "e2e.staff@globx.co.in", second)).status()).toBe(403)
  await recPage.goto("/admin/monitor")
  await expect(recPage).toHaveURL(/\/login/)
  await rec.close()

  // ten wrong passwords lock an account; Unlock opens it again
  for (let i = 0; i < 10; i++) await tryLogin(request, "e2e.staff@globx.co.in", "Wrong-pass-1")
  const api = await staffRequest(request, ORG)
  const me = (await api.get("/users")).find((u) => u.email === "e2e.staff@globx.co.in")
  await api.send("put", `/users/${me.id}`, { status: "active" })
  await page.reload()
  await expect(renamed).toContainText("Locked")
  await renamed.getByRole("button", { name: "Unlock E2E Staff Renamed" }).click()
  await expect(renamed).toContainText("Active")
  expect((await tryLogin(request, "e2e.staff@globx.co.in", second)).status()).toBe(200)
})

test("protections: a Super Admin's row is locked for an Org Admin, and nobody can disable or demote themselves", async ({ page }) => {
  await loginStaff(page, ORG)
  await page.goto("/admin/users")
  const rows = page.getByTestId("user-row")
  const boss = rows.filter({ hasText: "Super Admin" }).first()
  await expect(boss.getByRole("button", { name: /^Edit / })).toBeDisabled()
  await expect(boss.getByRole("button", { name: /^Change password for / })).toBeDisabled()

  await page.getByRole("button", { name: "Edit Org Admin" }).click()
  await expect(dialog(page).getByLabel("Status")).toBeDisabled()
  await expect(dialog(page).getByRole("checkbox", { name: "Org Admin" })).toBeDisabled()
  await expect(dialog(page)).toContainText("You cannot change your own roles")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()

  // a Super Admin sees the Super Admin role and can use it
  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)
  await loginStaff(page, "superadmin@globx.co.in")
  await page.goto("/admin/users")
  await page.getByRole("button", { name: "Add user" }).click()
  await expect(dialog(page).getByRole("checkbox", { name: "Super Admin" })).toBeVisible()
})

test("candidates are listed with their exams and can get a new password", async ({ page, request }) => {
  await loginStaff(page, ORG)
  await page.goto("/admin/users")
  await page.getByRole("tab", { name: /^Candidates/ }).click()
  const rows = page.getByTestId("user-row")
  const rahul = rows.filter({ hasText: "rahul" })
  await expect(rahul).toContainText("GLOBX Full-Stack Screening (Sample)")
  await page.getByLabel("Search users").fill("sneha")
  await expect(rows.filter({ hasText: "rahul" })).toHaveCount(0)
  await expect(rows.filter({ hasText: "sneha" })).toHaveCount(1)
  await shot(page, "users-candidates")
  await page.getByRole("button", { name: /^Change password for Sneha/ }).click()
  await dialog(page).getByLabel("New password").fill("Sneha-New-2026")
  await dialog(page).getByRole("button", { name: "Set password" }).click()
  await expect(dialog(page)).toHaveCount(0)
  expect((await tryLogin(request, "sneha", "Sneha-New-2026")).status()).toBe(200)
  expect((await tryLogin(request, "sneha", creds().candidate)).status()).toBe(401)
})

test("each role sees only what it may use", async ({ page }) => {
  // Recruiter: participants and the monitor, nothing that builds exams or reads answer keys
  await loginStaff(page, "recruiter@globx.co.in")
  await expect(nav(page, "Exams")).toBeVisible()
  await expect(nav(page, "Live monitor")).toBeVisible()
  for (const hidden of ["Question bank", "Users"]) await expect(nav(page, hidden)).toHaveCount(0)
  await expect(page.getByRole("link", { name: "New exam" })).toHaveCount(0)
  for (const path of ["/admin/users", "/admin/questions", "/admin/questions/new"]) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/admin$/)  // typed-in addresses are turned away
  }
  await page.getByRole("link", { name: "GLOBX Full-Stack Screening (Sample)" }).click()
  await expect(page.getByRole("button", { name: "Publish" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Unpublish" })).toHaveCount(0)
  await expect(page.getByLabel("Title", { exact: true })).toBeDisabled()  // the details can be read, not changed
  await expect(page.getByRole("button", { name: "Save exam" })).toHaveCount(0)
  await page.getByRole("tab", { name: "Questions" }).click()
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Build with AI" })).toHaveCount(0)
  await page.getByRole("tab", { name: "Participants" }).click()
  await expect(page.getByText("Add participants")).toBeVisible()  // this is what a recruiter is for
  await expect(page.getByRole("button", { name: /^Actions for / }).first()).toBeVisible()
  await page.getByRole("link", { name: "Departments" }).click()
  await expect(page.getByTestId("department-row").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "New department" })).toHaveCount(0)
  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)

  // Evaluator: reads the bank and watches, cannot change questions or manage participants
  await loginStaff(page, "evaluator@globx.co.in")
  await expect(nav(page, "Question bank")).toBeVisible()
  await expect(nav(page, "Users")).toHaveCount(0)
  await page.goto("/admin/questions")
  await expect(page.getByRole("row").nth(1)).toBeVisible()
  await expect(page.getByRole("button", { name: "New question" })).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0)
  await page.getByRole("link", { name: "Exams" }).click()
  await page.getByRole("link", { name: "GLOBX Full-Stack Screening (Sample)" }).click()
  await page.getByRole("tab", { name: "Participants" }).click()
  await expect(page.getByText("Add participants")).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Actions for / })).toHaveCount(0)
  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)

  // Test Creator: builds, but has no Users screen
  await loginStaff(page, "creator@globx.co.in")
  await expect(nav(page, "Question bank")).toBeVisible()
  await expect(nav(page, "Users")).toHaveCount(0)
  await expect(page.getByRole("link", { name: "New exam" })).toBeVisible()
  await shot(page, "users-creator-nav")
})

test("a server that predates roles (no permission list in /auth/me) gives a clear message, never a blank screen", async ({ page }) => {
  await loginStaff(page, ORG)
  await page.route("**/api/v1/auth/me", async (route) => {  // what an old backend answers
    const body = await (await route.fetch()).json()
    delete body.can
    await route.fulfill({ json: body })
  })
  await page.reload()
  await expect(page.getByRole("heading", { name: "The server needs a restart" })).toBeVisible()
  await expect(page.getByText("restart the backend")).toBeVisible()
  await shot(page, "users-old-server")
})
