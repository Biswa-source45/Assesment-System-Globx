import { expect, test } from "@playwright/test"
import { creds, login, loginStaff, shot, staffRequest } from "./helpers"

// Long lists come 50 at a time and load the next 50 when scrolled to the end; search and filters are answered by the server; a slow answer shows a
// round spinner in the page, in the corner and in the button. The data is made through the API (130 questions, 60 people), the checks are on real screens.
const slow = (ms) => async (route) => { await new Promise((r) => setTimeout(r, ms)); await route.continue() }
const more = (page) => page.getByTestId("more-rows")
const shownCount = (page) => page.getByTestId("shown-count")

async function bank(api, n, shorts = 3, word = "PagingBank") {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const make = (title, type) => api.post("/questions", { department_id: dept, type, title, body: "<p>x</p>", marks: 1,
    config: type === "short" ? { model_answer: "x", keywords: ["x"] } : { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  for (let i = 1; i <= n; i++) await make(`${word} ${String(i).padStart(3, "0")}`, "mcq_single")
  for (let i = 1; i <= shorts; i++) await make(`${word} short ${i}`, "short")
  return dept
}

async function exam(api, title, names, publish = true) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>x</p>", marks: 1,
    config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, shuffle_questions: false, shuffle_options: false })
  const section = (await api.post(`/tests/${t.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  if (publish) await api.post(`/tests/${t.id}/publish`)
  if (names) await api.post(`/tests/${t.id}/participants`, { names })
  return t
}

test("question bank: 50 at a time, the next 50 on scrolling, search and filters come from the server, an edit keeps the place", async ({ page, request }) => {
  const api = await staffRequest(request)
  await bank(api, 127, 3)                                                   // 130 questions with the title "PagingBank ..."
  await loginStaff(page)
  await page.goto("/admin/questions")
  const rows = page.locator("tbody tr")
  await page.getByLabel("Search questions").fill("PagingBank")
  await expect(shownCount(page)).toHaveText("Showing 50 of 130 questions")
  await expect(rows).toHaveCount(50)
  await shot(page, "paging-bank-first")
  await more(page).scrollIntoViewIfNeeded()                                // the end of the list comes into view: the next 50 are asked for
  await expect(shownCount(page)).toHaveText("Showing 100 of 130 questions")
  await more(page).scrollIntoViewIfNeeded()
  await expect(shownCount(page)).toHaveText("Showing 130 of 130 questions")
  await expect(rows).toHaveCount(130)
  await expect(more(page).getByRole("button", { name: "Load more" })).toHaveCount(0)  // everything is here
  const titles = await rows.locator("td:first-child").allTextContents()
  expect(new Set(titles).size).toBe(130)                                    // not one twice
  await shot(page, "paging-bank-all")

  await page.getByLabel("Search questions").fill("PagingBank short")       // the server searches, not the page
  await expect(shownCount(page)).toHaveText("Showing 3 of 3 questions")
  await expect(rows).toHaveCount(3)
  await page.getByLabel("Search questions").fill("PagingBank")
  await page.getByRole("combobox", { name: "Filter by type" }).click()
  await page.getByRole("option", { name: "Short answer" }).click()          // filter and search together
  await expect(shownCount(page)).toHaveText("Showing 3 of 3 questions")
  await page.getByLabel("Search questions").fill("no such question anywhere")
  await expect(page.getByText("No questions found.")).toBeVisible()
  await expect(more(page)).toHaveCount(0)

  // archiving one question keeps the list where it was: 100 loaded rows stay 100 rows, one fewer in all
  await page.getByLabel("Search questions").fill("PagingBank")
  await page.getByRole("combobox", { name: "Filter by type" }).click()
  await page.getByRole("option", { name: "All types" }).click()
  await expect(shownCount(page)).toHaveText("Showing 50 of 130 questions")
  await more(page).scrollIntoViewIfNeeded()
  await expect(shownCount(page)).toHaveText("Showing 100 of 130 questions")
  await rows.first().getByRole("button", { name: /Archive/ }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Archive", exact: true }).click()
  await expect(shownCount(page)).toHaveText("Showing 100 of 129 questions")
  await expect(rows).toHaveCount(100)
})

test("a second page that fails says so, keeps what is shown, and Try again loads it", async ({ page, request }) => {
  const api = await staffRequest(request)
  await bank(api, 60, 0, "FailBank")
  await loginStaff(page)
  let failing = true
  await page.route("**/api/v1/questions?*offset=50*", (route) => (failing ? route.abort() : route.continue()))
  await page.goto("/admin/questions")
  await page.getByLabel("Search questions").fill("FailBank")
  await expect(shownCount(page)).toHaveText("Showing 50 of 60 questions")
  await more(page).scrollIntoViewIfNeeded()
  await expect(more(page).getByRole("alert")).toBeVisible()
  await expect(page.locator("tbody tr")).toHaveCount(50)                    // the first page is still there
  failing = false
  await more(page).getByRole("button", { name: "Try again" }).click()
  await expect(page.locator("tbody tr")).toHaveCount(60)
  await expect(shownCount(page)).toHaveText("Showing 60 of 60 questions")
})

test("a slow answer shows round spinners in the page, in the corner and in the button; the 5-second refresh stays quiet", async ({ page }) => {
  await page.route("**/api/v1/auth/login", slow(1500))
  await page.goto("/login")
  await page.getByLabel("Username or email").fill("creator@globx.co.in")
  await page.getByLabel("Password", { exact: true }).fill(creds()["creator@globx.co.in"])
  await page.getByRole("button", { name: "Sign in" }).click()
  const button = page.getByRole("button", { name: "Signing in..." })
  await expect(button).toHaveAttribute("aria-busy", "true")                  // a round spinner inside the button, and it is off
  await expect(button).toBeDisabled()
  await expect(button.locator("svg.animate-spin")).toBeVisible()
  await expect(page).toHaveURL(/\/admin/)
  await page.unroute("**/api/v1/auth/login")

  await page.route("**/api/v1/questions?*", slow(1800))
  await page.goto("/admin/questions")
  await expect(page.getByText("Loading...").first()).toBeVisible()           // the page's own spinner while its first data is on the way
  await expect(page.getByTestId("busy-chip")).toBeVisible()                  // and the one in the corner: the answer took longer than 0.3 s
  await shot(page, "paging-spinners")
  await expect(page.locator("tbody tr").first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId("busy-chip")).toHaveCount(0)                 // gone when the answer is here
  await page.unroute("**/api/v1/questions?*")

  await page.route("**/api/v1/tests/*/monitor", slow(1500))                 // the live monitor asks again every 5 seconds
  await page.goto("/admin/monitor")
  await page.waitForTimeout(7500)                                            // past one refresh
  await expect(page.getByTestId("busy-chip")).toHaveCount(0)
})

test("users: staff and candidates are paged and searched by the server, and the tab counts are the totals", async ({ page, request }) => {
  const api = await staffRequest(request)
  const names = Array.from({ length: 60 }, (_, i) => `Pager Person ${String(i + 1).padStart(2, "0")}`)
  await exam(api, "Pager Users Exam", names)
  await loginStaff(page, "orgadmin@globx.co.in")
  await page.goto("/admin/users")
  await page.getByLabel("Search users").fill("Pager Person")
  await page.getByRole("tab", { name: /^Candidates/ }).click()
  await expect(page.getByRole("tab", { name: "Candidates (60)" })).toBeVisible()   // the total, not the 50 on screen
  await expect(shownCount(page)).toHaveText("Showing 50 of 60 candidates")
  await expect(page.getByTestId("user-row")).toHaveCount(50)
  await more(page).scrollIntoViewIfNeeded()
  await expect(shownCount(page)).toHaveText("Showing 60 of 60 candidates")
  await expect(page.getByTestId("user-row")).toHaveCount(60)
  await page.getByLabel("Search users").fill("Pager Users Exam")            // an exam title finds its candidates too
  await expect(page.getByRole("tab", { name: "Candidates (60)" })).toBeVisible()
  await page.getByLabel("Search users").fill("pager person 07")
  await expect(page.getByRole("tab", { name: "Candidates (1)" })).toBeVisible()
  await expect(page.getByTestId("user-row")).toHaveCount(1)
  await page.getByRole("tab", { name: /^Staff/ }).click()
  await page.getByLabel("Search users").fill("")
  await expect(page.getByTestId("user-row").filter({ hasText: "Lipsa Evaluator" })).toHaveCount(1)
})

test("an exam's participants and results come 50 at a time while the summary covers everyone; the Results list asks for the summary only", async ({ page, request }) => {
  const api = await staffRequest(request)
  const names = Array.from({ length: 60 }, (_, i) => `Rows Person ${String(i + 1).padStart(2, "0")}`)
  const t = await exam(api, "Pager Rows Exam", names)
  await loginStaff(page)

  await page.goto(`/admin/exams/${t.id}?tab=participants`)
  await expect(shownCount(page)).toHaveText("Showing 50 of 60 people")
  await expect(page.locator("tbody tr").filter({ hasText: "Rows Person" })).toHaveCount(50)
  await more(page).scrollIntoViewIfNeeded()
  await expect(shownCount(page)).toHaveText("Showing 60 of 60 people")
  await page.getByLabel("Search participants").fill("rows person 07")
  await expect(shownCount(page)).toHaveText("Showing 1 of 1 people")

  const asked = []
  page.on("request", (r) => { if (/\/tests\/[^/]+\/results\?/.test(r.url())) asked.push(r.url()) })
  await page.goto("/admin/results")
  const row = page.getByTestId("results-exam").filter({ hasText: "Pager Rows Exam" })
  await expect(row).toContainText("0 of 60")                                  // the summary alone is enough for this list
  expect(asked.length).toBeGreaterThan(0)
  expect(asked.every((u) => u.includes("limit=0"))).toBe(true)

  await page.goto(`/admin/results/${t.id}`)
  await expect(page.getByTestId("summary-Assigned")).toHaveText("60")
  await expect(shownCount(page)).toHaveText("Showing 50 of 60 people")
  await expect(page.getByTestId("results-row")).toHaveCount(50)
  await more(page).scrollIntoViewIfNeeded()
  await expect(page.getByTestId("results-row")).toHaveCount(60)
  await expect(page.getByTestId("summary-Assigned")).toHaveText("60")        // the tiles do not depend on the page
  await page.getByLabel("Search the results").fill("rows person 33")
  await expect(page.getByTestId("results-row")).toHaveCount(1)
  await expect(page.getByTestId("summary-Assigned")).toHaveText("60")
  await shot(page, "paging-results")
})

test("the question picker inside an exam is paged too: 30 at a time, searched by the server", async ({ page, request }) => {
  const api = await staffRequest(request)
  await bank(api, 70, 0, "PickBank")
  const t = await exam(api, "Pager Picker Exam", null, false)               // a draft exam
  await loginStaff(page)
  await page.goto(`/admin/exams/${t.id}?tab=questions`)
  await page.getByRole("button", { name: "Add questions" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByTestId("shown-count")).toContainText("Showing 30 of")
  await expect(dialog.getByRole("checkbox")).toHaveCount(30)
  await dialog.getByTestId("more-rows").scrollIntoViewIfNeeded()
  await expect(dialog.getByTestId("shown-count")).toContainText("Showing 60 of")
  await dialog.getByLabel("Search the bank").fill("PickBank 06")
  await expect(dialog.getByTestId("shown-count")).toHaveText("Showing 10 of 10 questions")  // PickBank 060 to 069
  await dialog.getByRole("checkbox").first().click()
  await dialog.getByRole("button", { name: /Add 1 selected/ }).click()
  await expect(page.getByText("PickBank 0", { exact: false }).first()).toBeVisible()
  await expect(dialog).toHaveCount(0)
})
