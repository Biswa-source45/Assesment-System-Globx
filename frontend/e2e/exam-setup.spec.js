import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest, startProctoredExam, confirmDialog } from "./helpers"

// Publishing asks for confirmation in the app's own dialog.
const publish = async (page) => {
  await page.getByRole("button", { name: "Publish" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click()
}

const CODING = {
  type: "coding", title: "Setup: double it", body: "<p>Read n, print 2n.</p>", marks: 10,
  config: { languages: ["python"], reference: { language: "python", source: "n=int(input())\nprint(2*n)" } },
  cases: [{ visibility: "open", input: "2\n", expected: "4" }, { visibility: "hidden", input: "5\n", expected: "10" }],
}
const SQL = {
  type: "sql", title: "Setup: names", body: "<p>All names.</p>", marks: 10,
  config: { schema: "CREATE TABLE t (name TEXT);", seed: "", engines: ["sqlite"], ordered: true, reference_sql: "SELECT name FROM t ORDER BY name" },
  cases: [{ visibility: "open", input: "INSERT INTO t VALUES ('b'), ('a');" }, { visibility: "hidden", input: "INSERT INTO t VALUES ('z');" }],
}

test("admin builds an exam, adds people, publishes it; a candidate then takes it with the rules set in the form", async ({ page, browser, request }) => {
  const api = await staffRequest(request)  // two bank questions, prepared quickly; the server validates them when it saves them
  const technical = (await api.get("/departments")).find((d) => d.name === "Technical").id
  await api.post("/questions", { ...CODING, department_id: technical })
  await api.post("/questions", { ...SQL, department_id: technical })

  await loginStaff(page)
  await page.getByRole("link", { name: "New exam" }).click()
  await page.getByLabel("Title", { exact: true }).fill("E2E Setup Exam")
  await page.getByLabel("Time allowed per candidate (minutes)").fill("45")
  await page.getByLabel("Window or full-screen leaves allowed").fill("2")
  await shot(page, "exam-new")
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}\?tab=questions/)
  await expect(page.getByTestId("exam-status")).toHaveText("draft")

  // an empty exam cannot be published, and the page says what is missing
  await publish(page)
  await expect(page.getByTestId("publish-problems")).toContainText("Add at least one section")

  await page.getByLabel("New section title").fill("Part 1")
  await page.getByRole("button", { name: "Add section" }).click()
  await page.getByRole("button", { name: "Add questions" }).click()
  await page.getByLabel("Search the bank").fill("Setup:")
  await page.getByRole("checkbox", { name: /Setup: double it/ }).click()
  await page.getByRole("checkbox", { name: /Setup: names/ }).click()
  await page.getByRole("button", { name: /Add 2 selected/ }).click()
  await expect(page.getByTestId("exam-item")).toHaveCount(2)
  await expect(page.getByTestId("exam-totals")).toContainText("2 questions, 20 marks")
  await expect(page.getByTestId("publish-problems")).toHaveCount(0)  // the old "cannot publish" list goes away once the exam changes
  await page.getByLabel("Section 1 timer in minutes").fill("30")
  await page.getByLabel("Section 1 title").click()  // leaving the field saves it
  await shot(page, "exam-questions")

  // a question that is already in the exam cannot be picked twice
  await page.getByRole("button", { name: "Add questions" }).click()
  await page.getByLabel("Search the bank").fill("Setup: names")
  await expect(page.getByRole("checkbox", { name: /Setup: names/ })).toBeDisabled()
  await page.keyboard.press("Escape")

  await page.getByRole("tab", { name: "Participants" }).click()
  await page.getByLabel("Participant names").fill("Asha Rao\nVikram Das")
  await page.getByRole("button", { name: "Create logins" }).click()
  await confirmDialog(page, "Create")
  const sheet = page.getByTestId("credentials")
  await expect(sheet.getByTestId("cred-username")).toHaveCount(2)
  const username = await sheet.getByTestId("cred-username").first().innerText()
  const password = await sheet.getByTestId("cred-password").first().innerText()
  await expect(page.getByRole("row").filter({ hasText: "Asha Rao" }).filter({ hasText: "Not started" })).toHaveCount(1)  // the list, next to the one-time sheet
  await shot(page, "exam-participants")

  await publish(page)
  await expect(page.getByTestId("exam-status")).toHaveText("published")
  await page.getByRole("tab", { name: "Questions" }).click()
  await expect(page.getByText(/sections and questions are frozen/)).toBeVisible()
  await expect(page.getByRole("button", { name: "Add questions" })).toHaveCount(0)

  // the candidate, in their own browser window, with the login from the sheet
  const { ctx, page: cand } = await candidateWindow(browser)
  await startProctoredExam(cand, username, "E2E Setup Exam", password)
  await expect(cand.getByTestId("violations")).toHaveText("Warnings 0 / 2")  // the rule typed in the admin form reached the exam
  await expect(cand.getByTestId("timer")).toContainText(/^(44|45):/)         // 45 minutes
  await expect(cand.getByLabel("Question palette").getByRole("button")).toHaveCount(2)
  await ctx.close()

  await page.getByRole("tab", { name: "Participants" }).click()
  await expect(page.getByRole("row").filter({ hasText: "Asha Rao" }).filter({ hasText: "In progress" })).toHaveCount(1)
})

test("exam details: the schedule and proctoring rules are saved; a closing time before the opening time is refused", async ({ page }) => {
  await loginStaff(page)
  await page.goto("/admin/exams/new")
  await page.getByLabel("Title", { exact: true }).fill("E2E Schedule Exam")
  await page.getByLabel("Opens at").fill("2031-05-01T10:00")
  await page.getByLabel("Closes at").fill("2031-05-01T09:00")
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page.getByText("End must be after start")).toBeVisible()
  await expect(page).toHaveURL(/\/admin\/exams\/new/)

  await page.getByLabel("Closes at").fill("2031-05-01T12:00")
  await page.getByLabel("Face warnings before the exam ends and the login is locked").fill("4")
  await page.getByRole("button", { name: "Create exam" }).click()
  await expect(page).toHaveURL(/\/admin\/exams\/[0-9a-f]{32}/)
  await page.getByRole("tab", { name: "Details" }).click()
  await page.reload()
  await expect(page.getByLabel("Opens at")).toHaveValue("2031-05-01T10:00")
  await expect(page.getByLabel("Closes at")).toHaveValue("2031-05-01T12:00")
  await expect(page.getByLabel("Face warnings before the exam ends and the login is locked")).toHaveValue("4")

  await page.getByLabel("Proctoring on").click()  // switching it off hides the detailed rules
  await expect(page.getByLabel("Window or full-screen leaves allowed")).toHaveCount(0)
  await page.getByRole("button", { name: "Save exam" }).click()
  await expect(page.getByText("Exam saved")).toBeVisible()
  await page.reload()
  await expect(page.getByLabel("Window or full-screen leaves allowed")).toHaveCount(0)
})

test("the exams list fits a laptop screen without sideways scrolling, its action buttons are coloured and scrollbars are thin", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await loginStaff(page)
  await page.goto("/admin/exams")
  await expect(page.locator("table").getByRole("link", { name: "Open", exact: true }).first()).toBeVisible()
  const wide = await page.locator('[data-slot="table-container"]').evaluate((e) => e.scrollWidth - e.clientWidth)
  expect(wide, "the table must not need a sideways scrollbar").toBeLessThanOrEqual(0)
  const bg = (loc) => loc.evaluate((e) => getComputedStyle(e).backgroundColor)
  expect(await bg(page.locator("table").getByRole("link", { name: "Open", exact: true }).first())).not.toBe("rgba(0, 0, 0, 0)")
  expect(await page.locator("table").getByRole("link", { name: "Monitor" }).first().evaluate((e) => getComputedStyle(e).color)).toBe("rgb(29, 78, 216)")
  expect(await page.evaluate(() => getComputedStyle(document.documentElement, "::-webkit-scrollbar").width)).toBe("8px")
  await shot(page, "exams-list")
})
