import { expect, test } from "@playwright/test"
import { loginStaff, shot, staffRequest } from "./helpers"

// The Help screen: topics, search, deep links, and the four playgrounds, on the real screens.
const topic = (page, title) => page.getByTestId("topic").filter({ has: page.locator("summary", { hasText: title }) })
const heading = (page, title) => page.locator("summary", { hasText: title })
async function openHelp(page, who) {
  await loginStaff(page, who)
  await page.locator("[data-sidebar=sidebar]").getByText("Help", { exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/help/)
  await expect(page.getByRole("heading", { name: "Help", level: 1 })).toBeVisible()
}
const play = async (page, title) => { await heading(page, title).click(); return topic(page, title) }
const editor = (box) => box.getByTestId("playground-editor").locator(".cm-content")
async function type(box, text) {  // replace what is in the code box (insertText skips the editor's auto-closing of brackets)
  await editor(box).click()
  await box.page().keyboard.press("ControlOrMeta+A")
  await box.page().keyboard.insertText(text)
}

test("the Help item is in the sidebar; topics open and close; open all / close all", async ({ page }) => {
  await openHelp(page)
  await expect(page.getByTestId("topic").first()).toBeVisible()
  expect(await page.getByTestId("topic").count()).toBeGreaterThanOrEqual(20)
  for (const t of ["The big picture", "The question types", "The JSON file: structure", "JSON for coding questions", "Check my JSON", "Try the exam screen", "Try a coding question", "Try an SQL question"])
    await expect(heading(page, t)).toBeVisible()
  const first = topic(page, "The big picture")
  await expect(first).not.toHaveAttribute("open", "")
  await heading(page, "The big picture").click()
  await expect(first).toHaveAttribute("open", "")
  await expect(first.getByTestId("diagram")).toBeVisible()  // the diagram is there
  await heading(page, "The big picture").click()
  await expect(first).not.toHaveAttribute("open", "")
  await page.getByRole("button", { name: "Open all" }).click()
  await expect(page.locator("details[open]")).toHaveCount(await page.getByTestId("topic").count())
  await page.getByRole("button", { name: "Close all" }).click()
  await expect(page.locator("details[open]")).toHaveCount(0)
  await shot(page, "help-closed")
})

test("search finds topics by any word in them, hides the rest, says so when nothing matches, and Clear restores", async ({ page }) => {
  await openHelp(page)
  const total = await page.getByTestId("topic").count()
  await page.getByLabel("Search help").fill("negative marks")
  const types = topic(page, "The question types")
  await expect(types).toBeVisible()
  await expect(types).toHaveAttribute("open", "")  // a match opens
  await expect(topic(page, "Create an exam, step by step")).toBeHidden()
  await expect(page.getByTestId("help-count")).toContainText("match")
  await page.getByLabel("Search help").fill("hidden test case")  // words from inside a topic, not its title
  await expect(topic(page, "JSON for coding questions")).toBeVisible()
  await page.getByLabel("Search help").fill("zzzzqq")
  await expect(page.getByTestId("help-count")).toContainText("No topic matches")
  await expect(page.getByTestId("topic").locator("visible=true")).toHaveCount(0)
  await page.getByLabel("Search help").fill("(.*[")  // symbols are plain text, never a pattern: no crash
  await expect(page.getByTestId("help-count")).toContainText("No topic matches")
  await page.getByRole("button", { name: "Clear" }).click()
  await expect(page.getByTestId("topic").locator("visible=true")).toHaveCount(total)
  await expect(page.getByLabel("Search help")).toHaveValue("")
})

test("a link with ?topic= opens that topic; the bank and the Build with AI dialog link to the help", async ({ page, request }) => {
  await loginStaff(page)
  await page.goto("/admin/help?topic=json-route")
  await expect(topic(page, "Upload many questions: the AI route")).toHaveAttribute("open", "")
  await page.goto("/admin/help?topic=does-not-exist")  // an unknown topic is ignored
  await expect(page.getByRole("heading", { name: "Help", level: 1 })).toBeVisible()
  await expect(page.locator("details[open]")).toHaveCount(0)

  await page.goto("/admin/questions")
  await page.getByRole("link", { name: "Question help" }).click()
  await expect(page).toHaveURL(/topic=question-types/)
  await expect(topic(page, "The question types")).toHaveAttribute("open", "")

  const api = await staffRequest(request)
  const dept = (await api.get("/departments")).find((d) => d.name === "General").id
  const exam = await api.post("/tests", { department_id: dept, title: "E2E Help Link", duration_min: 30, settings: { proctoring: { enabled: false } } })
  await page.goto(`/admin/exams/${exam.id}`)
  await page.getByRole("tab", { name: "Questions" }).click()
  await page.getByRole("button", { name: "Build with AI" }).click()
  const link = page.getByRole("dialog").getByRole("link", { name: "Format help and samples" })
  await expect(link).toHaveAttribute("href", /\/admin\/help\?topic=json-route/)
  await expect(link).toHaveAttribute("target", "_blank")  // a new tab, so the pasted file is not lost
})

test("Check my JSON: the sample is accepted, a broken edit gets the real messages, nothing is saved", async ({ page, request }) => {
  const api = await staffRequest(request)
  const bank = async () => (await api.get("/questions?q=Prime%20number")).length
  const before = await bank()
  await openHelp(page)
  const box = await play(page, "Check my JSON")
  await expect(box.getByLabel("JSON to check")).not.toHaveValue("")
  await box.getByRole("button", { name: "Check (nothing is saved)" }).click()
  await expect(box.getByTestId("pack-preview")).toContainText("This file is correct and would import")
  await expect(box.getByTestId("pack-section")).toHaveCount(2)

  const text = await box.getByLabel("JSON to check").inputValue()
  await box.getByLabel("JSON to check").fill(text.replace('"c"', '"z"'))  // a right answer that is not an option
  await box.getByRole("button", { name: "Check (nothing is saved)" }).click()
  await expect(box.getByTestId("pack-errors")).toContainText("'z' is not one of the options")
  await expect(box.getByTestId("pack-errors")).toContainText("Section 1, question 1")

  await box.getByLabel("JSON to check").fill('{"sections": [}')  // not JSON at all
  await box.getByRole("button", { name: "Check (nothing is saved)" }).click()
  await expect(box.getByTestId("try-json-error")).toContainText("not valid JSON")

  await box.getByRole("button", { name: "Sample: every type" }).click()  // coding and SQL are really run
  await box.getByRole("button", { name: "Check (nothing is saved)" }).click()
  await expect(box.getByTestId("pack-section")).toHaveCount(6, { timeout: 60_000 })
  expect(await bank()).toBe(before)  // not one question was created
  await shot(page, "help-json-playground")
})

test("Try the exam screen: marks come from the real rule, incl. the wrong-tick and tick-everything cases", async ({ page }) => {
  await openHelp(page)
  const box = await play(page, "Try the exam screen")
  await box.getByRole("radio", { name: "7", exact: true }).check()
  await box.getByRole("button", { name: "Save and next" }).click()
  for (const n of ["2", "4", "3"]) await box.getByRole("checkbox", { name: n, exact: true }).check()  // both right ones plus a wrong one
  await box.getByRole("button", { name: "Mark for review" }).click()
  await box.getByRole("button", { name: "Save and next" }).click()
  await box.getByLabel("Your answer").fill("A column that identifies each row.")
  await box.getByRole("button", { name: "Finish" }).click()
  await expect(box.getByTestId("mark-1")).toHaveText("Marks: 1 of 1")
  await expect(box.getByTestId("mark-2")).toHaveText("Marks: 1.75 of 2")  // 2 right = 2, one wrong tick takes 0.25 off
  await expect(box.getByTestId("exam-total")).toHaveText("2.75")
  await expect(box.getByTestId("exam-sheet")).toContainText("marked by AI and then checked by a person")
  await shot(page, "help-exam-playground")
  await box.getByRole("button", { name: "Try again" }).click()
  await box.getByRole("button", { name: "Sample question 2" }).click()
  for (const n of ["2", "3", "4", "5"]) await box.getByRole("checkbox", { name: n, exact: true }).check()  // ticking everything cannot win
  await box.getByRole("button", { name: "Sample question 3" }).click()
  await box.getByRole("button", { name: "Finish" }).click()
  await expect(box.getByTestId("mark-2")).toHaveText("Marks: 0 of 2")
  await expect(box.getByTestId("mark-1")).toHaveText("Marks: 0 of 1")  // unanswered
})

test("Try a coding question: a right answer passes every case; a wrong one fails some; hidden cases show only a verdict", async ({ page }) => {
  await openHelp(page)
  const box = await play(page, "Try a coding question")
  await expect(box.getByRole("button", { name: "Run on all cases" })).toBeEnabled()  // the starter code is there
  await box.getByRole("button", { name: "Show a correct solution (Python)" }).click()
  await box.getByRole("button", { name: "Run on all cases" }).click()
  await expect(box.getByTestId("try-code-result")).toContainText("4 of 4 test cases passed", { timeout: 60_000 })
  await expect(box.getByTestId("try-code-case")).toHaveCount(4)

  await type(box, "print(0)")  // right only when the sum is 0
  await box.getByRole("button", { name: "Run on all cases" }).click()
  await expect(box.getByTestId("try-code-result")).toContainText("2 of 4 test cases passed", { timeout: 60_000 })
  await expect(box.getByTestId("try-code-case").nth(0)).toContainText("Failed")
  await expect(box.getByTestId("try-code-case").nth(1)).toContainText("Success")
  await expect(box.getByTestId("try-code-result")).not.toContainText("2000000000")  // the hidden case's data is not shown
  await expect(box.getByTestId("try-code-case").nth(3)).toContainText("Hidden case 2")
  await shot(page, "help-coding-playground")

  await type(box, "print(")  // a broken program
  await box.getByRole("button", { name: "Run on all cases" }).click()
  await expect(box.getByTestId("try-code-result")).toContainText("0 of 4 test cases passed", { timeout: 60_000 })
  await expect(box.getByTestId("try-code-case").first()).toContainText(/Compilation Error|Runtime Error/)
})

test("Try an SQL question: wrong query does not match, the right one matches, a syntax error is explained", async ({ page }) => {
  await openHelp(page)
  const box = await play(page, "Try an SQL question")
  await box.getByRole("button", { name: "Run", exact: true }).click()  // the starter query returns everybody
  await expect(box.getByTestId("try-sql-result")).toContainText("Does not match the expected output", { timeout: 60_000 })
  await box.getByRole("button", { name: "Show a correct query" }).click()
  await box.getByRole("button", { name: "Run", exact: true }).click()
  await expect(box.getByTestId("try-sql-result")).toContainText("Matches the expected output", { timeout: 60_000 })
  await expect(box.getByTestId("try-sql-result")).toContainText("Asha")
  await type(box, "SELECT name FROM employees WHERE salary >= 50000 ORDER BY name")  // the classic off-by-one: Dev earns exactly 50000
  await box.getByRole("button", { name: "Run", exact: true }).click()
  await expect(box.getByTestId("try-sql-result")).toContainText("Does not match", { timeout: 60_000 })
  await expect(box.getByTestId("try-sql-result")).toContainText("Dev")
  await shot(page, "help-sql-playground")
  await type(box, "SELEC name FROM employees")
  await box.getByRole("button", { name: "Run", exact: true }).click()
  await expect(box.getByTestId("try-sql-error")).toBeVisible({ timeout: 60_000 })
  await expect(box.getByTestId("try-sql-result")).toHaveCount(0)
})

test("a recruiter reads the topics and uses the exam screen, but the code playgrounds explain who may use them", async ({ page }) => {
  await openHelp(page, "recruiter@globx.co.in")
  const coding = await play(page, "Try a coding question")
  await expect(coding).toContainText("open to Test Creators and Org Admins")
  await expect(coding.getByRole("button", { name: "Run on all cases" })).toHaveCount(0)
  const json = await play(page, "Check my JSON")
  await expect(json).toContainText("open to Test Creators and Org Admins")
  const exam = await play(page, "Try the exam screen")
  await exam.getByRole("radio", { name: "7", exact: true }).check()
  await exam.getByRole("button", { name: "Sample question 3" }).click()
  await exam.getByRole("button", { name: "Finish" }).click()
  await expect(exam.getByTestId("mark-1")).toHaveText("Marks: 1 of 1")
})

test("on a phone nothing sticks out sideways, even with every topic open", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  await loginStaff(page)
  await page.goto("/admin/help")
  await page.getByRole("button", { name: "Open all" }).click()
  await expect(page.getByTestId("topic").last().getByRole("button", { name: /Run|Check/ }).first()).toBeVisible({ timeout: 30_000 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, "help-phone")
})
