import { expect, test } from "@playwright/test"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { BASE_URL, login, loginStaff, shot, signOut, staffRequest } from "./helpers"

// Mailing a new user their login, and the staff Profile (name, password, e-mail with a code sent to the old address).
// The test server's stand-in mail server writes every mail as a file, so the real mail text is checked here.
const mailDir = path.join(os.tmpdir(), "oap-e2e-storage", "mail")
const allMails = () => (fs.existsSync(mailDir) ? fs.readdirSync(mailDir).map((f) => fs.readFileSync(path.join(mailDir, f), "utf8")) : [])
const mailsTo = (to, subject) => allMails().filter((m) => new RegExp(`^To: ${to.replace(/[.]/g, "\\.")}\\s*$`, "m").test(m) && new RegExp(`^Subject: ${subject}`, "m").test(m))
function part(mail, type) {
  const at = mail.search(new RegExp(`Content-Type: ${type}`, "i"))
  const [head, ...rest] = mail.slice(at).split(/\r?\n\r?\n/)
  let body = rest.join("\n\n").split(/\r?\n--=+/)[0]
  if (/base64/i.test(head)) body = Buffer.from(body.replace(/\s+/g, ""), "base64").toString("utf8")
  else if (/quoted-printable/i.test(head)) body = body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)))
  return body
}
const ORG = "orgadmin@globx.co.in"
const dialog = (page) => page.getByRole("dialog")
const tryLogin = (request, email, password) => request.post("/api/v1/auth/login", { data: { email, password } })

test("a new user can be mailed their login: Not now sends nothing, Send mails the email, password and link", async ({ page, request }) => {
  await loginStaff(page, ORG)
  await page.goto("/admin/users")
  const make = async (name, email) => {
    await page.getByRole("button", { name: "Add user" }).click()
    await dialog(page).getByLabel("Name").fill(name)
    await dialog(page).getByLabel("Email").fill(email)
    await dialog(page).getByRole("checkbox", { name: "Recruiter" }).click()
    await dialog(page).getByRole("button", { name: "Generate" }).click()
    const password = await dialog(page).getByLabel("First password").inputValue()
    await dialog(page).getByRole("button", { name: "Create user" }).click()
    return password
  }

  // Not now: the person exists and nothing is mailed
  await make("Nora NotNow", "nora.notnow@globx.co.in")
  await expect(dialog(page)).toContainText("Do you want to send the login details to nora.notnow@globx.co.in by e-mail?")
  await shot(page, "users-send-login")
  await dialog(page).getByRole("button", { name: "Not now" }).click()
  await expect(dialog(page)).toHaveCount(0)
  await expect(page.getByTestId("user-row").filter({ hasText: "Nora NotNow" })).toHaveCount(1)
  await page.waitForTimeout(1500)
  expect(mailsTo("nora.notnow@globx.co.in", "Your KAUTILYA login")).toHaveLength(0)

  // Send: one mail with the email, the password the screen made, the role and the link
  const password = await make("Sam Sent", "sam.sent@globx.co.in")
  await dialog(page).getByRole("button", { name: "Send by e-mail" }).click()
  await expect(page.getByText("Login details queued for sam.sent@globx.co.in")).toBeVisible()
  await expect(dialog(page)).toHaveCount(0)
  await expect.poll(() => mailsTo("sam.sent@globx.co.in", "Your KAUTILYA login").length, { timeout: 30000 }).toBe(1)
  const mail = mailsTo("sam.sent@globx.co.in", "Your KAUTILYA login")[0]
  for (const text of [part(mail, "text/plain"), part(mail, "text/html")]) {
    for (const x of ["Sam Sent", "sam.sent@globx.co.in", password, "Recruiter", "/login", "My profile"]) expect(text).toContain(x)
  }
  expect((await tryLogin(request, "sam.sent@globx.co.in", password)).status()).toBe(200)   // the mailed password really works

  // a new password offers the mail too, and mails the new one
  await page.getByRole("button", { name: "Change password for Sam Sent" }).click()
  await dialog(page).getByRole("button", { name: "Generate" }).click()
  const second = await dialog(page).getByLabel("New password").inputValue()
  await dialog(page).getByRole("button", { name: "Set password" }).click()
  await expect(dialog(page)).toContainText("New password set")
  await dialog(page).getByRole("button", { name: "Send by e-mail" }).click()
  await expect.poll(() => mailsTo("sam.sent@globx.co.in", "Your KAUTILYA login").length, { timeout: 30000 }).toBe(2)
  expect(mailsTo("sam.sent@globx.co.in", "Your KAUTILYA login").some((m) => part(m, "text/plain").includes(second))).toBe(true)
  // the outbox keeps the record but not the password
  const outbox = await (await staffRequest(request, ORG)).get("/system/outbox")
  expect(outbox.filter((m) => m.kind === "staff_login").every((m) => !m.body.includes(second) && !m.body.includes(password))).toBe(true)
})

test("the profile: sidebar link, name, password, and an e-mail that changes only with the code sent to the old address", async ({ page, request }) => {
  const api = await staffRequest(request, ORG)
  await api.post("/users", { email: "pat.profile@globx.co.in", name: "Pat Profile", roles: ["evaluator"], password: "Profile-Start-1" })
  await login(page, "pat.profile@globx.co.in", "Profile-Start-1")
  await page.getByTestId("my-profile").click()
  await expect(page).toHaveURL(/\/admin\/profile$/)
  await expect(page.getByTestId("profile-email")).toHaveText("pat.profile@globx.co.in")
  await expect(page.getByTestId("profile").getByText("Evaluator", { exact: true })).toBeVisible()
  await shot(page, "profile")

  // name: the sidebar follows at once
  await page.getByLabel("Name", { exact: true }).fill("Pat Renamed")
  await page.getByRole("button", { name: "Save name" }).click()
  await expect(page.getByText("Your name was saved")).toBeVisible()
  await expect(page.locator("[data-sidebar=sidebar]").getByText("Pat Renamed")).toBeVisible()

  // password: two refusals in plain words, then it works
  await page.getByLabel("Current password").fill("not-my-password-1")
  await page.getByLabel("New password", { exact: true }).fill("Profile-Next-2")
  await page.getByLabel("New password again").fill("Profile-Other-3")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByText("The two new passwords are not the same")).toBeVisible()
  await page.getByLabel("New password again").fill("Profile-Next-2")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByText("Current password is wrong")).toBeVisible()
  await page.getByLabel("Current password").fill("Profile-Start-1")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByText("Your password was changed")).toBeVisible()
  expect((await tryLogin(request, "pat.profile@globx.co.in", "Profile-Start-1")).status()).toBe(401)
  expect((await tryLogin(request, "pat.profile@globx.co.in", "Profile-Next-2")).status()).toBe(200)

  // e-mail: an address that is taken is refused; a wrong code changes nothing; the right one does
  await page.getByRole("button", { name: "Change e-mail" }).click()
  await dialog(page).getByLabel("New e-mail").fill("recruiter@globx.co.in")
  await dialog(page).getByRole("button", { name: "Send code" }).click()
  await expect(dialog(page)).toContainText("already exists")
  await dialog(page).getByLabel("New e-mail").fill("pat.moved@globx.co.in")
  await dialog(page).getByRole("button", { name: "Send code" }).click()
  await expect(dialog(page)).toContainText("p***e@globx.co.in")
  await expect(dialog(page).getByRole("button", { name: /Send a new code \(\d+ s\)/ })).toBeDisabled()
  await expect(dialog(page).getByRole("button", { name: "Change e-mail" })).toBeDisabled()                  // a code of six digits is needed
  await expect.poll(() => mailsTo("pat.profile@globx.co.in", "Your code to change").length, { timeout: 30000 }).toBe(1)   // to the OLD address
  expect(mailsTo("pat.moved@globx.co.in", "Your code to change")).toHaveLength(0)                          // nothing to the new one
  const code = /Your code: (\d{6})/.exec(part(mailsTo("pat.profile@globx.co.in", "Your code to change")[0], "text/plain"))[1]
  await dialog(page).getByLabel("Code").fill(code === "000000" ? "111111" : "000000")
  await dialog(page).getByRole("button", { name: "Change e-mail" }).click()
  await expect(dialog(page)).toContainText("Wrong code. 4 attempts left")
  await shot(page, "profile-email-code")
  await dialog(page).getByLabel("Code").fill(code)
  await dialog(page).getByRole("button", { name: "Change e-mail" }).click()
  await expect(page.getByText("Your e-mail was changed")).toBeVisible()
  await expect(page.getByTestId("profile-email")).toHaveText("pat.moved@globx.co.in")
  await expect.poll(() => mailsTo("pat.profile@globx.co.in", "Your KAUTILYA e-mail was changed").length, { timeout: 30000 }).toBe(1)   // the old address is told
  expect((await tryLogin(request, "pat.moved@globx.co.in", "Profile-Next-2")).status()).toBe(200)
  expect((await tryLogin(request, "pat.profile@globx.co.in", "Profile-Next-2")).status()).toBe(401)

  // the Users list shows the new address; an administrator cannot move their own e-mail from there
  await signOut(page)
  await loginStaff(page, ORG)
  await page.goto("/admin/users")
  await page.getByLabel("Search users").fill("Pat Renamed")
  await expect(page.getByTestId("user-row")).toHaveCount(1)   // the search is on the server: wait until the list is narrowed
  await expect(page.getByTestId("user-row")).toContainText("pat.moved@globx.co.in")
  await page.getByLabel("Search users").fill("")
  await page.getByRole("button", { name: /^Edit Org Admin/ }).click()
  await dialog(page).getByLabel("Email").fill("someone.else@globx.co.in")
  await dialog(page).getByRole("button", { name: "Save user" }).click()
  await expect(dialog(page)).toContainText("My profile")
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
})

test("the profile works on a phone screen", async ({ browser }) => {
  const ctx = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 390, height: 800 } })
  const page = await ctx.newPage()
  await loginStaff(page, "recruiter@globx.co.in")
  await page.goto("/admin/profile")
  await expect(page.getByRole("heading", { name: "My profile" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await page.getByRole("button", { name: "Change e-mail" }).click()
  await expect(dialog(page)).toBeVisible()
  await dialog(page).getByRole("button", { name: "Cancel" }).click()
  await ctx.close()
})
