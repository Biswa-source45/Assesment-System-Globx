import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { expect, test } from "@playwright/test"
import { confirmDialog, login, loginStaff, shot, signOut, staffRequest } from "./helpers"

// The report card: staff declare the results (the PDF is e-mailed to those who have an address), download one card and all cards, and a candidate who only has a
// login signs in, reads the card on screen and downloads the PDF. The mail server is a stand-in that writes every mail as a file (tests/e2e_server.py).
const mailDir = path.join(os.tmpdir(), "oap-e2e-storage", "mail")
const mails = () => (fs.existsSync(mailDir) ? fs.readdirSync(mailDir).map((f) => fs.readFileSync(path.join(mailDir, f), "utf8")) : [])
const cardMails = (to) => mails().filter((m) => m.includes(`To: ${to}`) && /Subject: Your report card/.test(m))
const dialog = (page) => page.getByRole("dialog")

async function asCandidate(request, username, password) {
  const auth = await (await request.post("/api/v1/auth/login", { data: { email: username, password } })).json()
  const headers = { Authorization: "Bearer " + auth.access_token }
  const call = async (method, p, data) => { const r = await request[method](`/api/v1${p}`, { headers, data }); expect(r.ok(), `${method} ${p}: ${await r.text()}`).toBeTruthy(); return r.json() }
  return { get: (p) => call("get", p), post: (p, d) => call("post", p, d), put: (p, d) => call("put", p, d) }
}

async function makeExam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, body: "<p>x</p>", type: "mcq_single", title: `${title} mcq`, marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, cutoff: 1, shuffle_questions: false, shuffle_options: false })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

async function sit(api, request, examId, line, pick) {
  const p = (await api.post(`/tests/${examId}/participants`, { names: [line] })).participants[0]
  const c = await asCandidate(request, p.username, p.password)
  const { attempt_id: at } = await c.post(`/assignments/${p.assignment_id}/start`, { consent: { accepted: true }, system_check: {} })
  const state = await c.get(`/attempts/${at}`)
  await c.put(`/attempts/${at}/answers/${state.sections[0].questions[0].id}`, { response: { selected: [pick] }, flagged: false, seq: 1 })
  await c.post(`/attempts/${at}/submit`, {})
  await expect.poll(async () => (await c.get(`/attempts/${at}`)).attempt.status, { timeout: 30_000 }).toMatch(/review_pending|evaluated/)
  return { ...p, at }
}

const pdfOf = async (download) => fs.readFileSync(await download.path())

test("declaring e-mails the PDF to candidates with an address; staff download cards; a login-only candidate reads and downloads theirs", async ({ page, request }) => {
  const creator = await staffRequest(request)                                                      // makes the exam and its participants
  const staff = await staffRequest(request, "evaluator@globx.co.in")                                // calculates and declares
  const exam = await makeExam(creator, "E2E Card Exam")
  const priya = await sit(creator, request, exam.id, "Priya Mailed, priya.mailed@example.com", "a")
  await sit(creator, request, exam.id, "Karan Wrong, karan.wrong@example.com", "b")
  const only = await sit(creator, request, exam.id, "Login Only", "a")
  await staff.post(`/tests/${exam.id}/calculate`)
  await expect.poll(async () => (await staff.get(`/tests/${exam.id}/results`)).calculated_at, { timeout: 30_000 }).toBeTruthy()

  await loginStaff(page, "evaluator@globx.co.in")
  await page.goto(`/admin/results/${exam.id}`)
  await expect(page.getByTestId("results-state")).toHaveText("Ready to declare")
  await expect(page.getByTestId("mail-summary")).toHaveCount(0)                                   // nothing is sent before declaring
  expect(cardMails("priya.mailed@example.com")).toHaveLength(0)

  // a preview card can be downloaded before the results are declared; the exam's ZIP holds every card
  const one = page.waitForEvent("download")
  await page.getByRole("button", { name: "Report card of Priya Mailed" }).click()
  const preview = await one
  expect(preview.suggestedFilename()).toBe("report-card-Priya-Mailed-E2E-Card-Exam.pdf")
  expect((await pdfOf(preview)).subarray(0, 5).toString()).toBe("%PDF-")
  const zip = page.waitForEvent("download")
  await page.getByRole("button", { name: "Report cards (ZIP)" }).click()
  const z = await zip
  expect(z.suggestedFilename()).toBe("report-cards-E2E-Card-Exam.zip")
  expect((await pdfOf(z)).subarray(0, 2).toString()).toBe("PK")

  // declaring says what it will do, then sends
  await page.getByRole("button", { name: "Declare results" }).click()
  await expect(dialog(page)).toContainText("sent the report card as a PDF")
  await confirmDialog(page, "Declare")
  await expect(page.getByText("2 report card(s) are being e-mailed")).toBeVisible()
  await expect(page.getByTestId("mail-summary")).toContainText("2 sent", { timeout: 45_000 })
  await expect(page.getByTestId("mail-summary")).toContainText("1 without an e-mail address")
  const row = (name) => page.getByTestId("results-row").filter({ hasText: name })
  await expect(row("Priya Mailed").getByTestId("mail-status")).toHaveText("Emailed")
  await expect(row("Karan Wrong").getByTestId("mail-status")).toHaveText("Emailed")
  await expect(row("Login Only").getByTestId("mail-status")).toHaveText("No e-mail")
  await shot(page, "report-card-results")

  // the mail itself: the right sender and address, a text body, and a real PDF attached; nothing for the login-only candidate
  const [mail] = cardMails("priya.mailed@example.com")
  expect(mail).toContain("From: KAUTILYA <support@globx.co.in>")
  expect(mail).toMatch(/Content-Type: application\/pdf/)
  expect(mail).toContain('filename="report-card-Priya-Mailed-E2E-Card-Exam.pdf"')
  const b64 = /Content-Type: application\/pdf[\s\S]*?\r?\n\r?\n([A-Za-z0-9+/=\r\n]+)/.exec(mail)[1].replace(/\s+/g, "")
  expect(Buffer.from(b64, "base64").subarray(0, 5).toString()).toBe("%PDF-")
  expect(cardMails("karan.wrong@example.com")).toHaveLength(1)
  expect(mails().filter((m) => /To: .*@exam\.local/.test(m) && /Your report card/.test(m))).toHaveLength(0)

  // pressing the button again sends nothing twice
  await page.getByRole("button", { name: "E-mail report cards" }).click()
  await confirmDialog(page, "Send")
  await expect(page.getByText("0 report card(s) are being e-mailed")).toBeVisible()
  await expect(async () => expect(cardMails("priya.mailed@example.com")).toHaveLength(1)).toPass()
  await signOut(page)

  // the candidate who only has a login: the card on the home page, on screen, and as a PDF
  await login(page, only.username, only.password)
  const result = page.getByTestId("my-result")
  await expect(result).toContainText("1 / 1")
  const dl = page.waitForEvent("download")
  await result.getByRole("button", { name: "Download PDF" }).click()
  expect((await dl).suggestedFilename()).toBe("report-card-Login-Only-E2E-Card-Exam.pdf")
  await result.getByRole("link", { name: "View report card" }).click()
  const card = page.getByTestId("report-card")
  await expect(card.getByTestId("rc-name")).toHaveText("Login Only")
  await expect(card.getByTestId("rc-exam")).toHaveText("E2E Card Exam")
  await expect(card.getByTestId("rc-score")).toHaveText("1 / 1")
  await expect(card.getByTestId("rc-result")).toHaveText("Passed")
  await expect(card).toContainText("RANK")
  await expect(card.getByTestId("rc-bar").first()).toContainText("1 / 1")
  await expect(card.getByTestId("rc-question")).toHaveCount(1)
  await expect(card.getByTestId("rc-question")).toContainText("Correct")
  await expect(card).not.toContainText("Preview")
  await shot(page, "report-card-screen")
  const again = page.waitForEvent("download")
  await card.getByRole("button", { name: "Download PDF" }).click()
  expect((await pdfOf(await again)).subarray(0, 5).toString()).toBe("%PDF-")

  // the phone: nothing runs off the side
  await page.setViewportSize({ width: 360, height: 800 })
  await page.reload()
  await expect(card.getByTestId("rc-name")).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, "report-card-phone")

  // withdrawn: the card is gone again, with a plain reason
  await staff.post(`/tests/${exam.id}/declare`, { declared: false })
  await page.reload()
  await expect(page.getByRole("alert")).toContainText("have not been declared")
  await expect(page.getByTestId("rc-name")).toHaveCount(0)
  expect(priya.at).toBeTruthy()
})
