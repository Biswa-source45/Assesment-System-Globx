import { expect, test } from "@playwright/test"
import { login, loginStaff, shot, staffRequest } from "./helpers"

// Analytics: a reviewer reads the whole exam (Results > Analytics tab) and one candidate against the class; a candidate reads their own analytics and sees their progress.
const RIGHT = "Zebra-right", WRONG = "Yak-wrong"
// Q1 is worth 2 marks, Q2 3, Q3 1. Q3 has a bad key: the strong answer b, the weak a (so the question is flagged).
const CLASS = [["Cand P1", "aab"], ["Cand P2", "aab"], ["Cand P3", "abb"], ["Cand P4", "abb"], ["Cand P5", "bab"], ["Cand P6", "bba"], ["Cand P7", "bba"], ["Cand P8", "---"]]

async function asCandidate(request, username, password) {
  const auth = await (await request.post("/api/v1/auth/login", { data: { email: username, password } })).json()
  const headers = { Authorization: "Bearer " + auth.access_token }
  const call = async (method, p, data) => { const r = await request[method](`/api/v1${p}`, { headers, data }); expect(r.ok(), `${method} ${p}: ${await r.text()}`).toBeTruthy(); return r.json() }
  return { get: (p) => call("get", p), post: (p, d) => call("post", p, d), put: (p, d) => call("put", p, d) }
}

async function makeExam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, cutoff: 3, shuffle_questions: false, shuffle_options: false })
  const spec = [["Part A", [[`${title} Q1`, 2, "easy", ["python"]], [`${title} Q2`, 3, "hard", ["python", "sql"]]]], ["Part B", [[`${title} Q3`, 1, "medium", ["sql"]]]]]
  for (const [name, qs] of spec) {
    const sid = (await api.post(`/tests/${exam.id}/sections`, { title: name })).sections.at(-1).id
    for (const [qt, marks, difficulty, skills] of qs) {
      const q = await api.post("/questions", { department_id: dept, body: "<p>x</p>", type: "mcq_single", title: qt, marks, difficulty, skills, config: { options: [{ id: "a", text: RIGHT, correct: true }, { id: "b", text: WRONG, correct: false }] } })
      await api.post(`/sections/${sid}/items`, { kind: "question", question_id: q.id })
    }
  }
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

async function sit(api, request, examId, name, picks) {
  const p = (await api.post(`/tests/${examId}/participants`, { names: [name] })).participants[0]
  const c = await asCandidate(request, p.username, p.password)
  const { attempt_id: at } = await c.post(`/assignments/${p.assignment_id}/start`, { consent: { accepted: true }, system_check: {} })
  const state = await c.get(`/attempts/${at}`)
  const qs = state.sections.flatMap((s) => s.questions)
  for (const [i, q] of qs.entries()) if (picks[i] !== "-") await c.put(`/attempts/${at}/answers/${q.id}`, { response: { selected: [picks[i]] }, flagged: false, seq: 1 })
  await c.post(`/attempts/${at}/submit`, {})
  await expect.poll(async () => (await c.get(`/attempts/${at}`)).attempt.status, { timeout: 30_000 }).toMatch(/review_pending|evaluated/)
  return { ...p, at }
}

async function finish(staff, examId) {
  await staff.post(`/tests/${examId}/calculate`)
  await expect.poll(async () => (await staff.get(`/tests/${examId}/results`)).calculated_at, { timeout: 30_000 }).toBeTruthy()
}

const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)

test("a reviewer reads the analytics of the whole exam and of one candidate", async ({ page, request }) => {
  const creator = await staffRequest(request)
  const staff = await staffRequest(request, "evaluator@globx.co.in")
  const exam = await makeExam(creator, "E2E Analytics")
  const people = {}
  for (const [name, picks] of CLASS) people[name] = await sit(creator, request, exam.id, name, picks)

  // before the results are calculated the numbers are shown, with a warning that they can still change
  await loginStaff(page, "evaluator@globx.co.in")
  await page.goto(`/admin/results/${exam.id}`)
  await page.getByRole("tab", { name: "Analytics" }).click()
  await expect(page).toHaveURL(/tab=analytics/)
  await expect(page.getByTestId("exam-analytics")).toBeVisible()
  await expect(page.getByTestId("aa-provisional")).toContainText("not calculated yet")

  await finish(staff, exam.id)
  const api = await staff.get(`/tests/${exam.id}/analytics`)
  await page.goto(`/admin/results/${exam.id}?tab=analytics`)                                    // a link straight to the tab
  const view = page.getByTestId("exam-analytics")
  await expect(view).toBeVisible()
  await expect(page.getByTestId("aa-provisional")).toHaveCount(0)

  // the screen shows exactly what the server worked out
  await expect(page.getByTestId("at-finished").getByTestId("tile-value")).toHaveText("8")
  await expect(page.getByTestId("at-mean").getByTestId("tile-value")).toHaveText(`${api.scores.mean}%`)
  const counts = await page.getByTestId("aa-score-hist").getByTestId("hist-bin").evaluateAll((g) => g.map((x) => Number(x.getAttribute("data-count"))))
  expect(counts).toEqual(api.score_distribution)
  expect(counts.reduce((a, b) => a + b, 0)).toBe(8)
  await expect(page.getByTestId("aa-score-hist").getByTestId("hist-mark")).toHaveCount(2)       // the average and the pass mark
  await expect(page.getByTestId("aa-time-hist").getByTestId("hist-bin")).toHaveCount(10)
  await expect(page.getByTestId("aa-scatter").getByTestId("scatter-dot")).toHaveCount(8)
  await expect(page.getByTestId("aa-funnel")).toContainText("Passed")
  await expect(page.getByTestId("aa-sections").getByTestId("rc-bar")).toHaveCount(2)
  await expect(page.getByTestId("aa-kinds")).toContainText("Choice")
  await expect(page.getByTestId("aa-difficulty")).toContainText("Hard")
  await expect(page.getByTestId("aa-skills")).toContainText("Python")
  await expect(page.getByTestId("aa-integrity")).toBeVisible()
  await expect(page.getByTestId("aa-marking")).toContainText("24 answers were marked by the platform")

  // the questions: Q3 has a bad key and is the one that needs a look
  const rows = page.getByTestId("aq-row")
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText("E2E Analytics Q1")
  await expect(rows.nth(2)).toHaveAttribute("data-health", "check the key")
  await expect(rows.nth(2)).toContainText("Check the key")
  await rows.nth(0).getByRole("button", { name: "Show how the options were chosen" }).click()
  const options = rows.nth(0).getByTestId("aq-options")
  await expect(options).toContainText(RIGHT)
  await expect(options).toContainText("Right answer")
  await shot(page, "analytics-exam")
  await page.getByLabel("Only questions that need a look").check()
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText("E2E Analytics Q3")

  // the Results tab is still there
  await page.getByRole("tab", { name: "Results" }).click()
  await expect(page.getByTestId("results-row")).toHaveCount(8)

  // the phone: nothing runs off the side
  await page.goto(`/admin/results/${exam.id}?tab=analytics`)
  await page.setViewportSize({ width: 360, height: 800 })
  await expect(page.getByTestId("exam-analytics")).toBeVisible()
  expect(await noSideScroll(page)).toBe(true)
  await shot(page, "analytics-exam-phone")
  await page.setViewportSize({ width: 1280, height: 720 })

  // one candidate against the class, opened from their review page
  await page.goto(`/admin/results/${exam.id}/${people["Cand P5"].at}`)
  await page.getByRole("link", { name: "Analytics" }).click()
  const one = page.getByTestId("attempt-analytics")
  await expect(one.getByTestId("aa-name")).toHaveText("Cand P5")
  await expect(one.getByTestId("aa-standing")).toContainText("Rank 3 of 8")
  await expect(one.getByTestId("aa-standing")).toContainText("higher than 71%")
  await expect(one).toContainText("Preview: the results have not been declared yet")               // staff may look before the declaration
  await page.getByRole("link", { name: "Back to the candidate" }).click()
  await expect(page.getByRole("heading", { name: "Cand P5" })).toBeVisible()

  // nobody has finished: an empty exam says so
  const empty = await makeExam(creator, "E2E Analytics Empty")
  await page.goto(`/admin/results/${empty.id}?tab=analytics`)
  await expect(page.getByTestId("aa-empty")).toContainText("No candidate has finished yet")
  await expect(page.getByTestId("at-finished").getByTestId("tile-value")).toHaveText("0")
})

test("a candidate reads their own analytics and sees their progress, and never the key or another person", async ({ page, request }) => {
  const creator = await staffRequest(request)
  const staff = await staffRequest(request, "evaluator@globx.co.in")
  const exam = await makeExam(creator, "E2E Analytics Own")
  const people = {}
  for (const [name, picks] of CLASS) people[name] = await sit(creator, request, exam.id, name, picks)
  await finish(staff, exam.id)
  const me = people["Cand P5"]

  // not declared: a plain reason, the address works for nobody else
  await login(page, me.username, me.password)
  await expect(page.getByRole("heading", { name: "Your exams" })).toBeVisible()
  await expect(page.getByTestId("my-progress")).toHaveCount(0)
  await page.goto(`/exam/analytics/${me.at}`)
  await expect(page.getByRole("alert")).toContainText("have not been declared")

  await staff.post(`/tests/${exam.id}/declare`, { declared: true })
  await page.goto("/exam")
  const progress = page.getByTestId("my-progress")
  await expect(progress).toBeVisible()
  await expect(progress.getByTestId("line-dot")).toHaveCount(1)                                   // one exam: a dot
  await expect(progress).toContainText("50")
  await page.getByTestId("my-result").getByRole("link", { name: "View analytics" }).click()

  const view = page.getByTestId("attempt-analytics")
  await expect(view.getByTestId("aa-name")).toHaveText("Cand P5")
  await expect(view.getByTestId("aa-standing")).toContainText("Rank 3 of 8")
  await expect(view.getByTestId("aa-standing")).toContainText("higher than 71%")
  const counts = await view.getByTestId("aa-histogram").getByTestId("hist-bin").evaluateAll((g) => g.map((x) => Number(x.getAttribute("data-count"))))
  expect(counts).toEqual([1, 2, 0, 2, 0, 1, 0, 0, 2, 0])
  await expect(view.getByTestId("aa-histogram").getByTestId("hist-mark")).toHaveCount(2)          // the class average and "You"
  await expect(view.getByTestId("aa-sections").getByTestId("rc-bar")).toHaveCount(2)
  await expect(view.getByTestId("aa-sections")).toContainText("Part A")
  await expect(view.getByTestId("aa-sections")).toContainText("Most to improve: Part B")
  const q = view.getByTestId("aa-question")
  await expect(q).toHaveCount(3)
  await expect(q.nth(0)).toContainText("Incorrect")
  await expect(q.nth(1)).toContainText("Correct")
  await expect(q.nth(1)).toContainText("38%")                                                    // a share of the class that got it right
  await expect(page.getByText("Preview: the results have not been declared")).toHaveCount(0)

  // the page holds nothing it should not
  const text = await page.locator("body").innerText()
  expect(text).not.toContain(RIGHT)
  expect(text).not.toContain(WRONG)
  for (const [name] of CLASS) if (name !== "Cand P5") expect(text).not.toContain(name)
  await shot(page, "analytics-candidate")

  // another candidate's analytics cannot be opened
  await page.goto(`/exam/analytics/${people["Cand P1"].at}`)
  await expect(page.getByRole("alert")).toContainText("not found")

  // links between the report card and the analytics
  await page.goto(`/exam/analytics/${me.at}`)
  await page.getByRole("link", { name: "Report card" }).click()
  await expect(page.getByTestId("report-card")).toBeVisible()
  await page.getByRole("link", { name: "View analytics" }).click()
  await expect(page.getByTestId("attempt-analytics")).toBeVisible()

  // the phone
  await page.setViewportSize({ width: 360, height: 800 })
  await page.reload()
  await expect(page.getByTestId("attempt-analytics")).toBeVisible()
  expect(await noSideScroll(page)).toBe(true)
  await shot(page, "analytics-candidate-phone")
  await page.goto("/exam")
  await expect(page.getByTestId("my-progress")).toBeVisible()
  expect(await noSideScroll(page)).toBe(true)
  await shot(page, "analytics-progress-phone")

  // withdrawn: gone again
  await staff.post(`/tests/${exam.id}/declare`, { declared: false })
  await page.goto(`/exam/analytics/${me.at}`)
  await expect(page.getByRole("alert")).toContainText("have not been declared")
  await page.goto("/exam")
  await expect(page.getByTestId("my-progress")).toHaveCount(0)
})
