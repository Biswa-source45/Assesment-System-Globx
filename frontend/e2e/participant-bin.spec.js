import { expect, test } from "@playwright/test"
import { BASE_URL, confirmDialog, login, loginStaff, shot, staffRequest } from "./helpers"

// Deleting a participant (the bin, restore, delete for good), the Compare table of the results, and the Chrome/Edge notice.

async function candidate(request, username, password) {
  const auth = await (await request.post("/api/v1/auth/login", { data: { email: username, password } })).json()
  const headers = { Authorization: "Bearer " + auth.access_token }
  const call = async (method, path, data) => {
    const r = await request[method](`/api/v1${path}`, { headers, data })
    expect(r.ok(), `${method} ${path}: ${await r.text()}`).toBeTruthy()
    return r.json()
  }
  return { post: (p, d) => call("post", p, d), put: (p, d) => call("put", p, d) }
}

// Two sections, one question each (A is the right option). Proctoring is off so people can sit it through the API.
async function exam(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const mcq = (n) => api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} ${n}`, body: "<p>x</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const qs = [await mcq("one"), await mcq("two")]
  const t = await api.post("/tests", { department_id: dept, title, duration_min: 30, cutoff: 1, shuffle_questions: false, shuffle_options: false, settings: { proctoring: { enabled: false } } })
  for (const [i, q] of qs.entries()) {
    const sec = (await api.post(`/tests/${t.id}/sections`, { title: `Section ${"AB"[i]}` })).sections[i]
    await api.post(`/sections/${sec.id}/items`, { kind: "question", question_id: q.id })
  }
  await api.post(`/tests/${t.id}/publish`)
  return { id: t.id, title, questions: qs.map((q) => q.id) }
}

async function sits(request, api, ex, name, picks) {
  const p = (await api.post(`/tests/${ex.id}/participants`, { names: [name] })).participants[0]
  if (picks) {
    const c = await candidate(request, p.username, p.password)
    const at = (await c.post(`/assignments/${p.assignment_id}/start`, { consent: { accepted: true }, system_check: {} })).attempt_id
    for (const [i, pick] of picks.entries()) await c.put(`/attempts/${at}/answers/${ex.questions[i]}`, { response: { selected: [pick] }, flagged: false, seq: 1 })
    await c.post(`/attempts/${at}/submit`, {})
  }
  return p
}

const rowOf = (page, name) => page.getByTestId("participant-row").filter({ hasText: name })

test("a participant is deleted to the bin, restored, and deleted for good after a confirmation", async ({ page, request }) => {
  const api = await staffRequest(request)
  const ex = await exam(api, "E2E Bin Exam")
  await sits(request, api, ex, "Asha Binner")
  await sits(request, api, ex, "Bala Keeper")
  await loginStaff(page)
  await page.goto(`/admin/exams/${ex.id}?tab=participants`)
  await expect(page.getByTestId("participant-row")).toHaveCount(2)
  await expect(page.getByTestId("bin-tab")).toHaveText("Bin")

  // delete: asked first; Cancel changes nothing
  await rowOf(page, "Asha Binner").getByRole("button", { name: "Actions for Asha Binner" }).click()
  await page.getByRole("menuitem", { name: "Delete participant" }).click()
  await expect(page.getByRole("dialog")).toContainText("Delete Asha Binner?")
  await confirmDialog(page, "Cancel")
  await expect(page.getByTestId("participant-row")).toHaveCount(2)
  await rowOf(page, "Asha Binner").getByRole("button", { name: "Actions for Asha Binner" }).click()
  await page.getByRole("menuitem", { name: "Delete participant" }).click()
  await confirmDialog(page, "Move to the bin")
  await expect(page.getByTestId("participant-row")).toHaveCount(1)
  await expect(page.getByTestId("participant-row")).toContainText("Bala Keeper")
  await expect(page.getByTestId("bin-tab")).toHaveText("Bin (1)")

  // the bin lists only her
  await page.getByTestId("bin-tab").click()
  await expect(page.getByTestId("bin-row")).toHaveCount(1)
  await expect(page.getByTestId("bin-row")).toContainText("Asha Binner")
  await shot(page, "participant-bin")
  await page.getByRole("button", { name: "Restore" }).click()
  await expect(page.getByText("The bin is empty.")).toBeVisible()
  await expect(page.getByTestId("bin-tab")).toHaveText("Bin")
  await page.getByTestId("list-tab").click()
  await expect(page.getByTestId("participant-row")).toHaveCount(2)

  // delete again, then for good: a dialog says what is lost, Cancel keeps her
  await rowOf(page, "Asha Binner").getByRole("button", { name: "Actions for Asha Binner" }).click()
  await page.getByRole("menuitem", { name: "Delete participant" }).click()
  await confirmDialog(page, "Move to the bin")
  await page.getByTestId("bin-tab").click()
  await page.getByRole("button", { name: "Delete for good" }).click()
  await expect(page.getByRole("dialog")).toContainText("cannot be undone")
  await shot(page, "participant-delete-for-good")
  await confirmDialog(page, "Cancel")
  await expect(page.getByTestId("bin-row")).toHaveCount(1)
  await page.getByRole("button", { name: "Delete for good" }).click()
  await confirmDialog(page, "Delete for good")
  await expect(page.getByText("The bin is empty.")).toBeVisible()
  await page.getByTestId("list-tab").click()
  await expect(page.getByTestId("participant-row")).toHaveCount(1)
  // she is gone from the server too, not only from the screen
  const left = await (await staffRequest(request, "recruiter@globx.co.in")).get(`/tests/${ex.id}/candidates?deleted=true`)
  expect(left.total).toBe(0)
})

test("the Compare tab lists every student side by side, sorts on a click and leaves out the bin", async ({ page, request }) => {
  const api = await staffRequest(request)
  const ex = await exam(api, "E2E Compare Exam")
  const zoya = await sits(request, api, ex, "Zoya Top", ["a", "a"])     // 2 marks
  await sits(request, api, ex, "Bala Mid", ["a", "b"])                  // 1 mark
  await sits(request, api, ex, "Chitra Absent")                         // did not come
  await loginStaff(page)
  await page.goto(`/admin/results/${ex.id}?tab=compare`)
  const names = () => page.getByTestId("compare-row").evaluateAll((rows) => rows.map((r) => r.querySelector("td:nth-child(2)").textContent))
  await expect(page.getByTestId("compare-row")).toHaveCount(3)
  for (const h of ["Rank", "Name", "Score", "%", "Section A", "Section B", "Minutes", "Result", "Risk"]) await expect(page.getByRole("columnheader", { name: h, exact: true })).toBeVisible()
  expect((await names()).map((n) => n.split(" ")[0])).toEqual(["Zoya", "Bala", "Chitra"])   // by rank; the absent person last
  await expect(page.getByTestId("compare-row").first()).toContainText("2 / 2")
  await expect(page.getByTestId("compare-average")).toContainText("1.5")                    // (2 + 1) / 2 people who appeared
  await shot(page, "results-compare")

  await page.getByRole("button", { name: "Name", exact: true }).click()                     // A to Z
  expect((await names()).map((n) => n.split(" ")[0])).toEqual(["Bala", "Chitra", "Zoya"])
  await page.getByRole("button", { name: "Name", exact: true }).click()                     // Z to A
  expect((await names()).map((n) => n.split(" ")[0])).toEqual(["Zoya", "Chitra", "Bala"])
  await page.getByRole("button", { name: "Section B", exact: true }).click()                // strongest in Section B first; the absent person never above a score
  expect((await names()).map((n) => n.split(" ")[0])).toEqual(["Zoya", "Bala", "Chitra"])
  await page.getByLabel("Search the comparison").fill("bala")
  await expect(page.getByTestId("compare-row")).toHaveCount(1)
  await page.getByLabel("Search the comparison").fill("")

  // a deleted student is not in the comparison, and the average follows
  await api.send("delete", `/assignments/${zoya.assignment_id}`)
  await page.reload()
  await expect(page.getByTestId("compare-row")).toHaveCount(2)
  await expect(page.getByTestId("compare-row").filter({ hasText: "Zoya" })).toHaveCount(0)
  await expect(page.getByTestId("compare-average")).toContainText("1")
  await page.getByRole("tab", { name: "Results" }).click()
  await expect(page.getByTestId("results-row")).toHaveCount(2)
  await expect(page.getByTestId("summary-Assigned")).toHaveText("2")
})

test("students are told to use Chrome or Edge: a notice on the login page, and a red one on the check-in page in another browser", async ({ page, browser, request }) => {
  await page.goto("/login")
  await expect(page.getByText("Use Google Chrome or Microsoft Edge.")).toBeVisible()
  const api = await staffRequest(request)
  const ex = await exam(api, "E2E Browser Exam")
  const p = await sits(request, api, ex, "Firefox Fan")

  await login(page, p.username, p.password)
  await page.locator("div[data-slot=card]").filter({ hasText: ex.title }).getByRole("link", { name: /Start|Resume/ }).click()
  await expect(page.getByTestId("browser-note")).toContainText("Use Google Chrome or Microsoft Edge for this exam")   // this browser is Chromium: a plain reminder

  const firefox = await browser.newContext({ baseURL: BASE_URL, userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0" })
  const f = await firefox.newPage()
  await login(f, p.username, p.password)
  await f.locator("div[data-slot=card]").filter({ hasText: ex.title }).getByRole("link", { name: /Start|Resume/ }).click()
  await expect(f.getByTestId("browser-note")).toContainText("You are not using Google Chrome or Microsoft Edge")
  await shot(f, "browser-notice-firefox")
  await firefox.close()
})
