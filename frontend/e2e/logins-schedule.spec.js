import { expect, test } from "@playwright/test"
import fs from "node:fs"
import { login, loginStaff, shot, staffRequest } from "./helpers"

const dialog = (page) => page.getByRole("dialog")

async function examWithOneQuestion(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>x</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30 })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

test("the login sheet keeps every batch, downloads them all, and can be had again for those who have not started", async ({ page, request }) => {
  const api = await staffRequest(request)
  const exam = await examWithOneQuestion(api, "E2E Login Sheet Exam")
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=participants`)
  const usernames = page.getByTestId("cred-username")
  const passwords = page.getByTestId("cred-password")
  const add = async (names) => {
    await page.getByLabel("Participant names").fill(names)
    await page.getByRole("button", { name: "Create logins" }).click()
  }
  const status = (u, p) => request.post("/api/v1/auth/login", { data: { email: u, password: p } }).then((r) => r.status())

  await add("Ila One")
  await expect(usernames).toHaveCount(1)
  await add("Jai Two\nKia Three")                                  // a second batch no longer wipes the first one
  await expect(usernames).toHaveCount(3)
  await expect(page.getByTestId("credentials")).toContainText("Ila One")
  const ids = await usernames.allInnerTexts()
  const pws = await passwords.allInnerTexts()
  await shot(page, "logins-all-batches")

  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: /Download all \(3\) as CSV/ }).click()
  const csv = fs.readFileSync(await (await download).path(), "utf8")
  for (let i = 0; i < 3; i++) { expect(csv).toContain(ids[i]); expect(csv).toContain(pws[i]) }  // everyone's id and password is in the file

  // Jai starts the exam, then a fresh sheet is asked for: it holds only the two who have not started
  const jaiToken = (await (await request.post("/api/v1/auth/login", { data: { email: ids[1], password: pws[1] } })).json()).access_token
  const jaiAssignment = (await api.get(`/tests/${exam.id}/candidates`)).rows.find((r) => r.username === ids[1]).assignment_id
  const started = await request.post(`/api/v1/assignments/${jaiAssignment}/start`, { headers: { Authorization: "Bearer " + jaiToken }, data: { consent: { accepted: true }, system_check: {} } })
  expect(started.ok()).toBeTruthy()
  await page.reload()
  await page.getByRole("button", { name: "Get a fresh login sheet" }).click()
  await dialog(page).getByRole("button", { name: "Get new passwords" }).click()
  await expect(page.getByText("2 new password(s) are on the sheet above")).toBeVisible()
  await expect(usernames).toHaveCount(2)
  const freshIds = await usernames.allInnerTexts()
  const fresh = Object.fromEntries(freshIds.map((u, i) => [u, null]))
  const freshPws = await passwords.allInnerTexts()
  freshIds.forEach((u, i) => { fresh[u] = freshPws[i] })
  expect(freshIds).not.toContain(ids[1])
  expect(await status(ids[0], pws[0])).toBe(401)                  // Ila's old password stopped...
  expect(await status(ids[0], fresh[ids[0]])).toBe(200)           // ...and the one on the new sheet works
  expect(await status(ids[2], pws[2])).toBe(401)
  expect(await status(ids[2], fresh[ids[2]])).toBe(200)
  expect(await status(ids[1], pws[1])).toBe(200)                  // Jai had started: his password is untouched
})

test("the admin changes the closing date and candidates can (or cannot) take the exam accordingly", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const exam = await examWithOneQuestion(api, "E2E Window Exam")
  const p = (await api.post(`/tests/${exam.id}/participants`, { names: ["Win Dow"] })).participants[0]
  const ctx = await browser.newContext({ baseURL: "http://localhost:5174" })
  const home = await ctx.newPage()
  await login(home, p.username, p.password)
  const card = home.locator("div[data-slot=card]").filter({ hasText: "E2E Window Exam" })
  await expect(card.getByRole("link", { name: "Start" })).toBeVisible()      // no dates: open

  await loginStaff(page)
  const setCloses = async (value) => {
    await page.goto(`/admin/exams/${exam.id}`)
    await page.getByLabel("Closes at").fill(value)
    await page.getByRole("button", { name: "Save exam" }).click()
    await expect(page.getByText("Exam saved")).toBeVisible()
  }
  const examRow = page.getByRole("row").filter({ hasText: "E2E Window Exam" })
  await setCloses("2020-01-01T10:00")                                         // closed, in the past
  await page.goto("/admin")
  await expect(examRow.getByTestId("exam-window")).toHaveText("Closed")
  await expect(examRow).toContainText("Jan 1, 2020")
  await home.reload()
  await expect(card).toContainText("The test window has closed")
  await expect(card.getByRole("link", { name: "Start" })).toHaveCount(0)
  await shot(home, "schedule-closed")

  await setCloses("2030-01-01T10:00")                                         // the admin moves it later: the same person can start
  await page.goto("/admin")
  await expect(examRow.getByTestId("exam-window")).toHaveText("Open now")
  await home.reload()
  await expect(card.getByRole("link", { name: "Start" })).toBeVisible()
  await ctx.close()
})
