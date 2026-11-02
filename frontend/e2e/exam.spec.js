import { expect, test } from "@playwright/test"
import { login, loginCandidate, newParticipant, shot, startProctoredExam } from "./helpers"

const SUM_OK = "a,b=map(int,input().split())\nprint(a+b)"
const SQL_OK = "SELECT c.name AS customer_name, SUM(o.amount) AS total FROM customers c JOIN orders o ON o.customer_id = c.id WHERE o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01' GROUP BY c.name ORDER BY total DESC, customer_name LIMIT 3"

// Text in the editor that has a colour other than the plain text colour: the tokens the syntax highlighting recognised.
const colouredTokens = (page) => page.locator(".cm-content").evaluate((el) => {
  const plain = getComputedStyle(el).color
  return [...el.querySelectorAll("span")].filter((s) => getComputedStyle(s).color !== plain).map((s) => s.textContent)
})

async function typeCode(page, code) {
  await page.locator(".cm-content").click()
  await page.keyboard.press("Control+A")
  await page.keyboard.type(code)
}

// Starts the unproctored practice test and opens its coding question ("Sum of Two Numbers").
async function openPracticeCode(page, user) {
  await loginCandidate(page, user)
  await page.locator("div[data-slot=card]").filter({ hasText: "Practice Test" }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Start exam" }).click()
  const palette = page.getByLabel("Question palette").getByRole("button")
  for (let i = 0; i < 3; i++) {
    await palette.nth(i).click()
    if (await page.locator(".cm-content").count()) return
  }
  throw new Error("no coding question found")
}

test("candidate: wrong password, then sign in and see own exams only", async ({ page }) => {
  await login(page, "sneha", "wrong-pass-1")
  await expect(page.getByText("Invalid email or password")).toBeVisible()
  await loginCandidate(page, "sneha")
  await expect(page.getByRole("heading", { name: "Your exams" })).toBeVisible()
  await expect(page.getByText("Practice Test")).toBeVisible()
  await shot(page, "candidate-home")
  await page.goto("/admin")  // candidates are kept out of the admin area
  await expect(page).toHaveURL(/\/exam$/)
})

test("practice exam end to end: answer every question, run and submit code, finish", async ({ page }) => {
  await loginCandidate(page, "sneha")
  await page.locator("div[data-slot=card]").filter({ hasText: "Practice Test" }).getByRole("link", { name: /Start|Resume/ }).click()
  await expect(page.getByText("This exam is not proctored")).toBeVisible()
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page).toHaveURL(/\/exam\/attempt\//)
  await expect(page.getByTestId("timer")).toContainText(/\d\d:\d\d/)
  await shot(page, "exam-runner")

  const palette = page.getByLabel("Question palette").getByRole("button")
  const n = await palette.count()
  expect(n).toBe(3)
  for (let i = 0; i < n; i++) {
    await palette.nth(i).click()
    if (await page.getByRole("radio").count()) {
      await page.getByRole("radio").first().click()
    } else if (await page.getByRole("textbox", { name: "Your answer" }).count()) {
      await page.getByRole("textbox", { name: "Your answer" }).fill("A unique key sent with a request so retries are detected and the same result is returned, avoiding duplicate effects.")
    } else {
      await typeCode(page, SUM_OK)
      await page.getByRole("button", { name: "Submit", exact: true }).click()
      await expect(page.getByText(/Score \d+(\.\d+)? \/ \d+(\.\d+)?/)).toBeVisible({ timeout: 60_000 })
    }
    await expect(page.getByText(/Saved \d/)).toBeVisible({ timeout: 10_000 })
  }
  for (let i = 0; i < n; i++) await expect(palette.nth(i)).toHaveClass(/bg-primary/)  // all three show as answered

  await page.getByRole("button", { name: "End exam" }).click()
  await expect(page.getByText("All questions are answered")).toBeVisible()
  await page.getByRole("button", { name: "Submit exam" }).click()
  await expect(page.getByTestId("done-title")).toHaveText("Exam submitted")

  await page.getByRole("link", { name: "Back to my exams" }).click()
  await expect(page.locator("div[data-slot=card]").filter({ hasText: "Practice Test" })).toContainText("Submitted")
  await expect(page.getByRole("link", { name: /Start|Resume/ })).toHaveCount(1)  // only the sample exam is still startable
})

test("code results: a loader per case, Success in green, private cases as plain blocks", async ({ page }) => {
  await openPracticeCode(page, "amit")
  // slow the judge down a little so the loaders can be seen
  await page.route("**/api/v1/submissions/*", async (route) => { await new Promise((z) => setTimeout(z, 1200)); await route.continue() })
  await typeCode(page, SUM_OK)
  const results = page.getByTestId("code-results")

  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(page.getByTestId("case-running")).toHaveCount(3)           // one loader per sample case
  await expect(results.getByText("Running...").first()).toBeVisible()
  await expect(results.getByText("Success")).toHaveCount(3, { timeout: 30_000 })
  await expect(results.getByText("AC", { exact: true })).toHaveCount(0)   // no raw verdict codes
  await expect(results.getByText("3 / 3 test cases passed")).toBeVisible()
  await expect(results.locator("span.bg-green-600").first()).toBeVisible()

  await page.getByRole("button", { name: "Submit", exact: true }).click()
  await expect(page.getByTestId("case-running")).toHaveCount(6)           // 3 samples + 3 private
  await expect(page.getByTestId("private-case")).toHaveCount(3, { timeout: 30_000 })
  for (const c of await page.getByTestId("private-case").all()) await expect(c).toContainText("Success")
  await expect(page.getByTestId("private-case").first()).toContainText("Private test case 1")
  await expect(page.locator("[data-testid=private-case] summary")).toHaveCount(0)  // not collapsible
  await expect(results.locator("details")).toHaveCount(3)                          // only the samples expand
  await expect(results.getByText("6 / 6 test cases passed")).toBeVisible()
  await shot(page, "exam-code-result")
})

test("a wrong answer shows Failed in red, an endless loop shows Time Limit Exceeded", async ({ page }) => {
  await openPracticeCode(page, "rahul")
  const results = page.getByTestId("code-results")
  await typeCode(page, "print(0)")
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(results.getByText("Failed").first()).toBeVisible({ timeout: 30_000 })
  await expect(results.locator("span.bg-destructive").first()).toBeVisible()
  await expect(results.getByText("Success")).toHaveCount(1)  // "0 0" -> 0 happens to be right

  await typeCode(page, "while True: pass")
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(results.getByText("Time Limit Exceeded").first()).toBeVisible({ timeout: 90_000 })
  await shot(page, "exam-code-tle")
})

test("SQL question: formatted tables, an editor, Failed then Success, private cases", async ({ page, request }) => {
  const p = await newParticipant(request, "Sql Tester")
  await startProctoredExam(page, p.username, "GLOBX Full-Stack Screening (Sample)", p.password)
  await page.getByRole("button", { name: /F - SQL/ }).click()
  await expect(page.getByRole("heading", { name: "Top customers by revenue (2025)" })).toBeVisible()

  // schema and sample data as tables, like LeetCode
  await expect(page.getByText("Input tables").first()).toBeVisible()
  await expect(page.getByRole("columnheader", { name: "city" }).first()).toBeVisible()
  await expect(page.getByRole("columnheader", { name: "amount" }).first()).toBeVisible()
  await expect(page.getByRole("columnheader", { name: "customer_name" }).first()).toBeVisible()  // expected output
  await expect(page.getByTestId("code-editor")).toBeVisible()
  await shot(page, "exam-sql")

  const results = page.getByTestId("code-results")
  await typeCode(page, "SELECT 1 AS x")
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(results.getByText("Failed")).toHaveCount(3, { timeout: 30_000 })

  await typeCode(page, "select 1 as x from customers")  // lower case counts too
  expect(await colouredTokens(page)).toEqual(expect.arrayContaining(["select", "as", "from"]))
  await typeCode(page, SQL_OK)
  expect(await colouredTokens(page)).toEqual(expect.arrayContaining(["SELECT", "FROM", "WHERE", "GROUP", "ORDER", "LIMIT"]))  // SQL gets colours like the other languages
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(results.getByText("Success")).toHaveCount(3, { timeout: 30_000 })
  await results.locator("details").first().locator("summary").click()
  await expect(results.getByText("Your output").first()).toBeVisible()
  await shot(page, "exam-sql-result")

  await page.getByRole("button", { name: "Submit", exact: true }).click()
  await expect(page.getByTestId("private-case")).toHaveCount(3, { timeout: 30_000 })
  await expect(results.getByText("Score 10 / 10")).toBeVisible()
})

// Rewrites the exam state the server sends, to play out an older or broken server.
async function tamperWithAttemptState(page, change) {
  await page.route(/\/api\/v1\/attempts\/[0-9a-f]+$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue()
    const res = await route.fetch()
    const data = await res.json()
    change(data)
    await route.fulfill({ response: res, json: data })
  })
}

test("a SQL question from an older server (no sample tables) still opens", async ({ page, request }) => {
  const p = await newParticipant(request, "Old Server")
  await tamperWithAttemptState(page, (d) => d.sections.forEach((s) => s.questions.forEach((q) => {
    if (q.type === "sql") q.open_cases.forEach((c) => { delete c.tables })
  })))
  const errors = []
  page.on("pageerror", (e) => errors.push(e.message))
  await startProctoredExam(page, p.username, "GLOBX Full-Stack Screening (Sample)", p.password)
  await page.getByRole("button", { name: /F - SQL/ }).click()
  await expect(page.getByRole("heading", { name: "Top customers by revenue (2025)" })).toBeVisible()
  await expect(page.getByTestId("code-editor")).toBeVisible()
  await expect(page.getByText("Sample 1").first()).toBeVisible()
  expect(errors).toEqual([])
})

test("a question that cannot be drawn shows a message and a Reload button, never a blank page", async ({ page, request }) => {
  const p = await newParticipant(request, "Broken Payload")
  await tamperWithAttemptState(page, (d) => d.sections.forEach((s) => s.questions.forEach((q) => {
    if (q.type.startsWith("mcq")) q.options = null
  })))
  await startProctoredExam(page, p.username, "GLOBX Full-Stack Screening (Sample)", p.password, false)
  await expect(page.getByRole("heading", { name: "Something went wrong on this screen" })).toBeVisible()
  await expect(page.getByText("Your answers are saved")).toBeVisible()
  await expect(page.getByRole("button", { name: "Reload" })).toBeVisible()
  await shot(page, "exam-crash-message")
})
