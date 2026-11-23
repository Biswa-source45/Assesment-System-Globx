import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest } from "./helpers"

// SQL script questions (the candidate's statements change the data, the author's checks are read) and backend API questions (a Flask app called
// in-process): the author's editor, and a candidate running and submitting both.

const SCHEMA = "CREATE TABLE courses (course_id INTEGER PRIMARY KEY, course_name TEXT NOT NULL, capacity INTEGER);"
const DATA = "INSERT INTO courses VALUES (10,'DBMS',30),(11,'OOP',25);"
const REFERENCE = "ALTER TABLE courses ADD COLUMN credits INTEGER;\nALTER TABLE courses ADD COLUMN enrolled INTEGER NOT NULL DEFAULT 0;"
const CHECKS = ["SELECT name FROM pragma_table_info('courses') ORDER BY cid", "SELECT course_id, credits, enrolled FROM courses ORDER BY course_id",
  "INSERT INTO courses (course_id, course_name, capacity, enrolled) VALUES (99, 'X', 5, NULL)"]
const FLASK = `from flask import Flask, jsonify
app = Flask(__name__)
courses = [{"id": 1, "name": "DBMS", "seats": 1}]


@app.route("/api/courses")
def listing():
    return jsonify(courses)


@app.route("/api/courses/<int:cid>/register", methods=["POST"])
def register(cid):
    for c in courses:
        if c["id"] == cid:
            if c["seats"] <= 0:
                return jsonify({"error": "course full"}), 400
            c["seats"] -= 1
            return jsonify(c)
    return jsonify({"error": "not found"}), 404
`
const editor = (page) => page.locator(".cm-content")

// the exam may be shuffled: open the question whose title ends with the word
async function openQuestion(page, word) {
  const heading = page.getByRole("heading", { name: new RegExp(`${word}$`) })
  if (await heading.isVisible()) return
  await page.getByLabel("Question palette").waitFor()   // the exam screen has loaded
  if (await heading.isVisible()) return
  for (const b of await page.getByLabel("Question palette").getByRole("button").all()) {
    await b.click()
    if (await heading.waitFor({ timeout: 2000 }).then(() => true, () => false)) return   // (waits for the screen to change: the last click used to be checked before it had)
  }
}

async function typeInto(page, code) {
  await editor(page).click()
  await page.keyboard.press("Control+A")
  await page.keyboard.insertText(code)
}

async function makeExam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { enabled: false } } })
  const pack = {
    format: "globx-exam-questions/1",
    sections: [{ title: "Backend", questions: [
      { type: "sql", title: `${title} script`, statement: "Add two columns to courses: credits (INTEGER) and enrolled (INTEGER, NOT NULL, default 0). The checks read the columns, the rows and a NOT NULL rule.", marks: 4,
        schema: SCHEMA, reference_sql: REFERENCE, checks: CHECKS, datasets: [{ data: DATA, visibility: "open" }, { data: "INSERT INTO courses VALUES (12,'ML',20);", visibility: "hidden" }] },
      { type: "coding", title: `${title} api`, statement: "Back end only. Start with course 1 DBMS and 1 seat. POST /api/courses/{id}/register takes a seat (200), or answers 400 when full and 404 for an unknown id.", marks: 6,
        languages: ["flask"], time_limit_ms: 5000, reference: { language: "flask", source: FLASK },
        test_cases: [{ input: "GET /api/courses\nPOST /api/courses/1/register", visibility: "open" },
          { input: "POST /api/courses/1/register\nPOST /api/courses/1/register\nPOST /api/courses/9/register", visibility: "hidden" }] },
    ] }],
  }
  await api.post(`/tests/${t.id}/import-questions`, { pack, dry_run: false })
  const items = (await api.get(`/tests/${t.id}`)).sections[0].items
  const [script, backend] = await Promise.all(items.map((it) => api.get(`/questions/${it.question_id ?? it.question.id}`)))
  await api.post(`/tests/${t.id}/publish`)
  const p = (await api.post(`/tests/${t.id}/participants`, { names: ["Script Person, script.person@mail.test"], email_required: true })).participants[0]
  return { script, backend, p }
}

test("the author sees a script question as a script (switch on, reference script, checks) and an API question explains its requests", async ({ page, request }) => {
  const api = await staffRequest(request)
  const { script, backend } = await makeExam(api, "E2E Script Author Exam")
  expect(script.config.validated).toBe(true)                                   // the server ran the reference script and the checks
  expect(backend.config.validated).toBe(true)                                  // and the reference app on the requests

  await loginStaff(page)
  await page.goto(`/admin/questions/${script.id}`)
  await expect(page.getByTestId("sql-script-switch")).toBeChecked()
  await expect(page.getByRole("heading", { name: "Reference script" }).or(page.getByText("Reference script").first())).toBeVisible()
  await expect(page.getByLabel("Reference script")).toHaveValue(REFERENCE)
  await expect(page.getByLabel("Check statements, one per line")).toHaveValue(CHECKS.join("\n"))
  await page.getByLabel("Check statements, one per line").fill(`${CHECKS.join("\n")}\nSELECT COUNT(*) FROM courses`)
  await page.getByRole("button", { name: "Run script and checks on all datasets" }).click()
  await expect(page.getByText("Expected output updated")).toBeVisible()
  await shot(page, "script-question-editor")
  await page.getByRole("button", { name: /Save question/ }).click()
  await expect(page).toHaveURL(/\/admin\/questions$/)
  const saved = await api.get(`/questions/${script.id}`)
  expect(saved.config.checks).toHaveLength(4)
  expect(saved.config.validated).toBe(true)

  await page.goto(`/admin/questions/${backend.id}`)
  await expect(page.getByRole("checkbox", { name: "Flask / FastAPI (backend API)" })).toBeChecked()
  await expect(page.getByTestId("api-hint")).toContainText("METHOD /path")
  await shot(page, "api-question-editor")
})

test("a candidate runs and submits a script question and a backend API question and sees what each check and each response gave", async ({ browser, request }) => {
  const api = await staffRequest(request)
  const { p } = await makeExam(api, "E2E Script Candidate Exam")
  const { ctx, page } = await candidateWindow(browser)
  await page.goto("/login")
  await page.getByLabel("Username or email").fill(p.username)
  await page.getByLabel("Password", { exact: true }).fill(p.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.locator("div[data-slot=card]").filter({ hasText: "E2E Script Candidate Exam" }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Start exam" }).click()

  await openQuestion(page, "script")
  // the script question: a note says what will happen, the wrong script fails and shows the checks, the right one passes
  await expect(page.getByTestId("script-note")).toContainText("Your statements run on a copy of the tables, then the checks run")
  await expect(editor(page)).toContainText("Write your statements here")
  await typeInto(page, "ALTER TABLE courses ADD COLUMN credits INTEGER;")
  await page.getByRole("button", { name: "Run on samples" }).click()
  const results = page.getByTestId("code-results")
  await expect(results.getByText("Failed").first()).toBeVisible({ timeout: 30_000 })
  await results.getByText("Sample 1").click()
  await expect(results).toContainText("SELECT course_id, credits, enrolled FROM courses ORDER BY course_id")   // the checks, with what this script left behind and what was expected
  await expect(results).toContainText("error: no such column")
  await shot(page, "script-run-wrong")
  await typeInto(page, REFERENCE)
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(results.getByText("Success")).toHaveCount(1, { timeout: 30_000 })
  await page.getByRole("button", { name: "Submit", exact: true }).click()
  await expect(results).toContainText("2 / 2 test cases passed", { timeout: 30_000 })
  await expect(results).toContainText("Score 4 / 4")

  // the backend question: the examples are requests and responses, the starter is a Flask app
  await openQuestion(page, "api")
  await expect(page.getByTestId("examples")).toContainText("Requests")
  await expect(page.getByTestId("examples")).toContainText("Expected responses")
  await expect(editor(page)).toContainText("app = Flask(__name__)")
  await typeInto(page, FLASK.replace('c["seats"] <= 0', 'c["seats"] < 0'))   // lets the seats go below zero
  await page.getByRole("button", { name: "Submit", exact: true }).click()
  await expect(results).toContainText("1 / 2 test cases passed", { timeout: 40_000 })
  await shot(page, "api-submit-partly-wrong")
  await typeInto(page, FLASK)
  await page.getByRole("button", { name: "Submit", exact: true }).click()
  await expect(results).toContainText("2 / 2 test cases passed", { timeout: 40_000 })
  await expect(results).toContainText("Score 6 / 6")
  await ctx.close()
})
