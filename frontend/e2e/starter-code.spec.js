import { expect, test } from "@playwright/test"
import { candidateWindow, loginStaff, shot, staffRequest } from "./helpers"

// A coding question never opens with an empty editor, the candidate sees the real examples before running anything,
// and the starter code survives editing the question.

const CASES = [{ visibility: "open", input: "2\n", expected: "4" }, { visibility: "hidden", input: "3\n", expected: "6" }]
const editor = (page) => page.locator(".cm-content")

async function codingExam(api, title, config) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", {
    department_id: dept, type: "coding", title: `${title} question`, body: "<p>Print double of n.</p>", marks: 10,
    config: { reference: { language: "python", source: "n=int(input())\nprint(2*n)" }, ...config }, cases: CASES,
  })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { enabled: false } } })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "Code" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${t.id}/publish`)
  const p = (await api.post(`/tests/${t.id}/participants`, { names: ["Starter Person"] })).participants[0]
  return { q, p }
}

// A candidate in a window of their own: signs in, opens the exam (not proctored here, so no camera step) and starts it.
async function candidateStarts(browser, p, title) {
  const { ctx, page } = await candidateWindow(browser)
  await page.goto("/login")
  await page.getByLabel("Username or email").fill(p.username)
  await page.getByLabel("Password").fill(p.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await page.locator("div[data-slot=card]").filter({ hasText: title }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Start exam" }).click()
  await expect(page.getByTestId("code-editor")).toBeVisible()
  return { ctx, page }
}

test("a question without starter code opens with a template, the examples are shown before running, and the starter runs as a wrong answer, not a crash", async ({ browser, request }) => {
  const api = await staffRequest(request)
  const { p } = await codingExam(api, "E2E Template Exam", { languages: ["python", "java"] })
  const { ctx, page } = await candidateStarts(browser, p, "E2E Template Exam")

  // never empty: a plain template that says how to read and print
  await expect(editor(page)).toContainText("write your code here")
  await expect(editor(page)).toContainText("print the answer with print")

  // the examples are on the screen before anything is run
  const examples = page.getByTestId("examples")
  await expect(examples).toContainText("Example 1")
  await expect(examples.locator("pre").nth(0)).toHaveText("2")
  await expect(examples.locator("pre").nth(1)).toHaveText("4")
  await expect(examples.locator("pre")).toHaveCount(2)                  // only the sample case, never the hidden one
  await shot(page, "starter-template")

  await page.getByLabel("Language").click()
  await page.getByRole("option", { name: "Java" }).click()
  await expect(editor(page)).toContainText("public class Main")
  await expect(editor(page)).toContainText("System.out.println")

  // the template reads nothing and prints nothing: the sample is a wrong answer, not an error
  await page.getByLabel("Language").click()
  await page.getByRole("option", { name: "Python 3" }).click()
  await page.getByRole("button", { name: "Run on samples" }).click()
  const results = page.getByTestId("code-results")
  await expect(results.getByText("Failed")).toHaveCount(1, { timeout: 30_000 })
  await expect(results.getByText("Success")).toHaveCount(0)
  await ctx.close()
})

test("starter code written by the question's author is what the candidate gets, and saving the question again keeps it", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const mine = "n = int(input())\n# TODO: print the double of n\n"
  const { q, p } = await codingExam(api, "E2E Own Starter Exam", { languages: ["python"], starter: { python: mine } })

  // editing the question in the editor and saving must not lose the starter (the editor used to rebuild the question without it)
  await loginStaff(page)
  await page.goto("/admin/questions")
  await page.getByRole("link", { name: "E2E Own Starter Exam question" }).click()
  const box = page.getByLabel("Starter code Python")
  await expect(box).toHaveValue(mine)
  await expect(page.getByLabel("Starter code Java")).toHaveCount(0)       // only the allowed languages
  await box.fill(mine + "# read n above\n")
  await shot(page, "starter-editor")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("Question saved")).toBeVisible()
  expect((await api.get(`/questions/${q.id}`)).config.starter.python).toBe(mine + "# read n above\n")

  // a starter that solves the question is refused with a plain message, nothing changes
  await page.getByRole("link", { name: "E2E Own Starter Exam question" }).click()
  await page.getByLabel("Starter code Python").fill("n = int(input())\nprint(2 * n)\n")
  await page.getByRole("button", { name: "Save question" }).click()
  await expect(page.getByText("already solves the question").first()).toBeVisible()
  expect((await api.get(`/questions/${q.id}`)).config.starter.python).toBe(mine + "# read n above\n")

  // the candidate gets exactly the author's starter
  const { ctx, page: cand } = await candidateStarts(browser, p, "E2E Own Starter Exam")
  await expect(editor(cand)).toContainText("TODO: print the double of n")
  await expect(editor(cand)).toContainText("read n above")
  await ctx.close()
})
