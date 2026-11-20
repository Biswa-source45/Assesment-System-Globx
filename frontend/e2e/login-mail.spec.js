import { expect, test } from "@playwright/test"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { candidateWindow, confirmDialog, loginStaff, shot, staffRequest } from "./helpers"

// Participants with an email, the student sheet, editing a person, and mailing the logins once the exam is published.
// The test server's stand-in mail server writes every mail as a file, so the real mail text is checked here.
const mailDir = path.join(os.tmpdir(), "oap-e2e-storage", "mail")
const allMails = () => (fs.existsSync(mailDir) ? fs.readdirSync(mailDir).map((f) => fs.readFileSync(path.join(mailDir, f), "utf8")) : [])
const loginMails = (to) => allMails().filter((m) => new RegExp(`^To: ${to.replace(/[.]/g, "\\.")}\\s*$`, "m").test(m) && /^Subject: Your login for/m.test(m))

// The text of one part of a mail (plain or html), whatever encoding the part uses.
function part(mail, type) {
  const at = mail.search(new RegExp(`Content-Type: ${type}`, "i"))
  const [head, ...rest] = mail.slice(at).split(/\r?\n\r?\n/)
  let body = rest.join("\n\n").split(/\r?\n--=+/)[0]
  if (/base64/i.test(head)) body = Buffer.from(body.replace(/\s+/g, ""), "base64").toString("utf8")
  else if (/quoted-printable/i.test(head)) body = body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)))
  return body
}

async function publishedExam(api, title, extra = {}) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>x</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { enabled: false } }, ...extra })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

const createLogins = async (page, text) => {
  await page.getByLabel("Participant names").fill(text)
  await page.getByRole("button", { name: "Create logins" }).click()
  await confirmDialog(page, "Create")
}
const row = (page, name) => page.getByTestId("participant-row").filter({ hasText: name })
const menu = async (page, name, item) => {
  await row(page, name).getByRole("button", { name: `Actions for ${name}` }).click()
  await page.getByRole("menuitem", { name: item }).click()
}

test("a sheet is uploaded and checked, a person is corrected, and nothing can be mailed while the exam is a draft", async ({ page, request }) => {
  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title: "E2E Sheet Exam", duration_min: 30, settings: { proctoring: { enabled: false } } })
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=participants`)

  await expect(page.getByTestId("publish-first")).toContainText("Publish the exam first")      // a draft: sending is off and says why
  await expect(page.getByRole("button", { name: /Send logins by email/ })).toBeDisabled()

  const sample = page.waitForEvent("download")                                                   // the sample sheet comes from the site
  await page.getByRole("button", { name: "Download sample sheet" }).click()
  const sampleText = fs.readFileSync(await (await sample).path(), "utf8")
  expect(sampleText.split(/\r?\n/)[0]).toBe("Full name,Email")
  expect(sampleText).toContain("@example.com")

  const file = test.info().outputPath("people.csv")                                              // a sheet: a sample row, two people, one without an email
  fs.writeFileSync(file, "Full name,Email\nAsha Sample,asha.sample@example.com\nSheet One,sheet.one@mail.test\nSheet Two,SHEET.TWO@mail.test\nNo Mail,\n")
  await page.getByLabel("Student sheet").setInputFiles(file)
  await expect(page.getByLabel("Participant names")).toHaveValue("Sheet One, sheet.one@mail.test\nSheet Two, sheet.two@mail.test")
  await expect(page.getByTestId("sheet-problems")).toContainText("Row 5: the email of No Mail is missing")
  await shot(page, "participants-sheet-read")

  await createLogins(page, "Only Name")                                                          // a typed line must carry its email
  await expect(page.getByTestId("add-error")).toContainText("Line 1: add the email")
  await expect(page.getByTestId("credentials")).toHaveCount(0)

  await createLogins(page, "Sheet One, sheet.one@mail.test\nSheet Two, sheet.two@mail.test")
  await expect(page.getByTestId("cred-username")).toHaveCount(2)
  await expect(row(page, "Sheet One").getByTestId("participant-email")).toHaveText("sheet.one@mail.test")
  await expect(row(page, "Sheet One").getByTestId("login-mail")).toContainText("Not sent")

  await menu(page, "Sheet One", "Edit details")                                                  // the name and the email can be corrected
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("Email").fill("sheet.two@mail.test")
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(dialog).toContainText("already used by another login")                          // another person's address is refused
  await dialog.getByLabel("Full name").fill("Sheet Uno")
  await dialog.getByLabel("Email").fill("Sheet.Uno@mail.test")
  await dialog.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Saved. No email was sent.")).toBeVisible()
  await expect(row(page, "Sheet Uno").getByTestId("participant-email")).toHaveText("sheet.uno@mail.test")
  await expect(row(page, "Sheet Uno").getByTestId("login-mail")).toContainText("Not sent")

  await menu(page, "Sheet Uno", "Mail details")
  await expect(page.getByTestId("mail-history")).toContainText("No login mail has been sent to this person yet.")
  await shot(page, "participants-edit-and-details")
  expect(loginMails("sheet.uno@mail.test")).toHaveLength(0)                                      // nothing was mailed
})

test("logins are mailed after publishing: the mail, the record beside each person, a corrected email, and an exam with dates", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await publishedExam(api, "E2E Mail Exam")
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=participants`)
  await createLogins(page, "Mail Asha, mail.asha@mail.test\nMail Ben, mail.ben@mail.test")
  await expect(page.getByTestId("cred-username")).toHaveCount(2)
  const sheetRow = (name) => page.getByTestId("credentials").getByRole("row").filter({ hasText: name })
  const oldPassword = await sheetRow("Mail Asha").getByTestId("cred-password").innerText()
  await expect(page.getByRole("button", { name: /Send logins by email \(2 waiting\)/ })).toBeEnabled()

  await page.getByRole("button", { name: /Send logins by email/ }).click()
  await expect(page.getByRole("dialog")).toContainText("Send logins to 2 people?")
  await confirmDialog(page, "Send logins")
  await expect(page.getByTestId("send-note")).toContainText("2 login mails are on its way")
  await expect(page.getByTestId("mail-summary")).toContainText("2 sent", { timeout: 45_000 })   // the background job delivers; the list looks again by itself
  await expect(row(page, "Mail Asha").getByTestId("login-mail")).toContainText("Sent")
  await expect(row(page, "Mail Asha").getByTestId("login-mail")).toContainText("to mail.asha@mail.test")
  await shot(page, "participants-mail-status")

  // the mail: addressed to her, with this exam's details, her new username and password, and the link that goes to the login page
  const [mail] = loginMails("mail.asha@mail.test")
  expect(mail).toContain("Subject: Your login for E2E Mail Exam")
  const text = part(mail, "text/plain"), html = part(mail, "text/html")
  const user = await sheetRow("Mail Asha").getByTestId("cred-username").innerText()
  const password = await sheetRow("Mail Asha").getByTestId("cred-password").innerText()
  expect(password).not.toBe(oldPassword)                                                          // the mailed password is a fresh one
  expect(text).toContain("Dear Mail Asha,")
  expect(text).toContain(`Username: ${user}`)
  expect(text).toContain(`Password: ${password}`)
  expect(text).toContain("Time allowed: 30 minutes")
  expect(text).toContain("no fixed date")                                                         // no dates on this exam
  expect(text).toMatch(new RegExp(`/login\\?exam=${exam.id}`))
  expect(html).toContain("Open your exam")
  expect(html).toContain(`Password:`)
  expect((await request.post("/api/v1/auth/login", { data: { email: user, password: oldPassword } })).status()).toBe(401)
  expect((await request.post("/api/v1/auth/login", { data: { email: user, password } })).status()).toBe(200)

  // Ben's email was wrong: correcting it mails nobody, and the screen says the new address has not been mailed
  await menu(page, "Mail Ben", "Edit details")
  await page.getByRole("dialog").getByLabel("Email").fill("mail.ben.new@mail.test")
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Saved. No email was sent: the login went to the old address")).toBeVisible()
  await expect(row(page, "Mail Ben").getByTestId("login-mail")).toContainText("Email changed: not sent")
  await expect(row(page, "Mail Ben").getByTestId("login-mail")).toContainText("mail.ben@mail.test")
  await expect(page.getByTestId("mail-summary")).toContainText("1 email changed")
  await expect(page.getByRole("button", { name: /Send logins by email \(1 waiting\)/ })).toBeEnabled()
  await page.waitForTimeout(2500)
  expect(loginMails("mail.ben.new@mail.test")).toHaveLength(0)

  await menu(page, "Mail Ben", "Email login")                                                    // one person: a new password to the new address
  await expect(page.getByRole("dialog")).toContainText("mail.ben.new@mail.test")
  await confirmDialog(page, "Send login")
  await expect(row(page, "Mail Ben").getByTestId("login-mail")).toContainText("to mail.ben.new@mail.test", { timeout: 45_000 })
  await expect(row(page, "Mail Ben").getByTestId("login-mail")).toContainText("Sent", { timeout: 45_000 })
  expect(loginMails("mail.ben.new@mail.test")).toHaveLength(1)
  expect(loginMails("mail.ben@mail.test")).toHaveLength(1)                                        // the old address got only the first one
  await menu(page, "Mail Ben", "Mail details")
  await expect(page.getByTestId("mail-history")).toContainText("mail.ben.new@mail.test")
  await expect(page.getByTestId("mail-history")).toContainText("mail.ben@mail.test")
  await page.keyboard.press("Escape")

  // an exam with dates says from when to when, in India time
  const dated = await publishedExam(api, "E2E Dated Mail Exam", { starts_at: "2030-01-15T04:30:00Z", ends_at: "2030-01-15T08:30:00Z" })
  await api.post(`/tests/${dated.id}/participants`, { names: ["Dated Dev, dated.dev@mail.test"], email_required: true })
  const sent = await api.post(`/tests/${dated.id}/send-logins`, {})
  expect(sent.queued).toBe(1)
  await expect.poll(() => loginMails("dated.dev@mail.test").length, { timeout: 45_000 }).toBe(1)
  expect(part(loginMails("dated.dev@mail.test")[0], "text/plain")).toContain("from 15 Jan 2030, 10:00 IST to 15 Jan 2030, 14:00 IST")
})

test("the link in the mail opens the login page and carries on to the exam; an exam that is not open yet stays on the list", async ({ browser, request }) => {
  const api = await staffRequest(request)
  const open = await publishedExam(api, "E2E Link Open Exam")
  const later = await publishedExam(api, "E2E Link Later Exam", { starts_at: new Date(Date.now() + 2 * 86_400_000).toISOString() })
  const [taker] = (await api.post(`/tests/${open.id}/participants`, { names: ["Link Taker, link.taker@mail.test"], email_required: true })).participants
  const [waiter] = (await api.post(`/tests/${later.id}/participants`, { names: ["Link Waiter, link.waiter@mail.test"], email_required: true })).participants

  const w = await candidateWindow(browser)
  await w.page.goto(`/login?exam=${open.id}`)
  await expect(w.page.getByText("Your exam opens as soon as you are signed in")).toBeVisible()
  await w.page.getByLabel("Username or email").fill(taker.username)
  await w.page.getByLabel("Password", { exact: true }).fill(taker.password)
  await w.page.getByRole("button", { name: "Sign in" }).click()
  await expect(w.page).toHaveURL(new RegExp(`/exam/${taker.assignment_id}/start`))               // straight to this exam
  await w.ctx.close()

  const l = await candidateWindow(browser)
  await l.page.goto(`/login?exam=${later.id}`)
  await l.page.getByLabel("Username or email").fill(waiter.username)
  await l.page.getByLabel("Password", { exact: true }).fill(waiter.password)
  await l.page.getByRole("button", { name: "Sign in" }).click()
  await expect(l.page.getByRole("heading", { name: "Your exams" })).toBeVisible()               // not open yet: the list says so
  await expect(l.page.getByText(/The test opens at/)).toBeVisible()
  await expect(l.page).toHaveURL(/\/exam$/)
  await l.ctx.close()

  const x = await candidateWindow(browser)                                                       // a link for an exam that is not theirs
  await x.page.goto("/login?exam=nothing-like-it")
  await x.page.getByLabel("Username or email").fill(taker.username)
  await x.page.getByLabel("Password", { exact: true }).fill(taker.password)
  await x.page.getByRole("button", { name: "Sign in" }).click()
  await expect(x.page.getByRole("heading", { name: "Your exams" })).toBeVisible()
  await expect(x.page.getByText("That exam is not on your list").first()).toBeVisible()
  await x.ctx.close()
})

test("a mail that was not delivered is shown with its reason", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await publishedExam(api, "E2E Failed Mail Exam")
  await api.post(`/tests/${exam.id}/participants`, { names: ["Fail Fran, fail.fran@mail.test"], email_required: true })
  await page.route(/\/tests\/[^/]+\/candidates\?/, async (route) => {                            // what the server would say after the mail server refused the address
    const r = await route.fetch()
    const body = await r.json()
    body.rows[0].login_mail = { state: "failed", to: "fail.fran@mail.test", at: "2026-11-20T09:00:00+00:00", error: "The mail server refused it: no such mailbox" }
    body.logins = { waiting: 1, queued: 0, sent: 0, failed: 1, changed: 0, no_email: 0 }
    await route.fulfill({ response: r, json: body })
  })
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=participants`)
  await expect(row(page, "Fail Fran").getByTestId("login-mail")).toContainText("Not delivered")
  await expect(row(page, "Fail Fran").getByTestId("login-mail")).toContainText("The mail server refused it: no such mailbox")
  await expect(page.getByTestId("mail-summary")).toContainText("1 not delivered")
  await shot(page, "participants-mail-failed")
})
