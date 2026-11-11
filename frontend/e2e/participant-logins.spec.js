import { expect, test } from "@playwright/test"
import fs from "node:fs"
import { candidateWindow, login, loginStaff, shot, staffRequest, confirmDialog } from "./helpers"

// The login page has an eye to check what was typed; exam logins are made from the name, the email is optional,
// and what the downloaded sheet says is exactly what signs the person in.

async function examWithOneQuestion(api, title) {
  const dept = (await api.get("/departments")).find((d) => d.name === "Technical").id
  const q = await api.post("/questions", { department_id: dept, type: "mcq_single", title: `${title} q`, body: "<p>x</p>", marks: 1, config: { options: [{ id: "a", text: "A", correct: true }, { id: "b", text: "B", correct: false }] } })
  const exam = await api.post("/tests", { department_id: dept, title, duration_min: 30, settings: { proctoring: { enabled: false } } })
  const section = (await api.post(`/tests/${exam.id}/sections`, { title: "All" })).sections[0]
  await api.post(`/sections/${section.id}/items`, { kind: "question", question_id: q.id })
  await api.post(`/tests/${exam.id}/publish`)
  return exam
}

test("the eye on the login page shows and hides the password", async ({ page }) => {
  await page.goto("/login")
  const box = page.getByLabel("Password", { exact: true })
  await box.fill("ash@globx472")
  await expect(box).toHaveAttribute("type", "password")
  await page.getByRole("button", { name: "Show password" }).click()
  await expect(box).toHaveAttribute("type", "text")
  await expect(box).toHaveValue("ash@globx472")
  await shot(page, "login-password-shown")
  await page.getByRole("button", { name: "Hide password" }).click()
  await expect(box).toHaveAttribute("type", "password")
  await expect(page.getByLabel("Username or email")).toHaveAttribute("autocapitalize", "none")  // phones must not capitalise the username
})

test("the eye stays exactly where it is while it is pressed", async ({ page }) => {
  await page.goto("/login")
  const eye = page.getByRole("button", { name: "Show password" })
  const before = await eye.boundingBox()
  const box = await page.getByLabel("Password", { exact: true }).boundingBox()
  expect(before.y + before.height / 2).toBeCloseTo(box.y + box.height / 2, 0)  // it sits in the middle of the box

  // hold it in the pressed (:active) state, which is when it used to drop by half its height
  const cdp = await page.context().newCDPSession(page)
  await cdp.send("DOM.enable")
  await cdp.send("CSS.enable")
  const { root } = await cdp.send("DOM.getDocument")
  const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: "button[aria-label='Show password']" })
  await cdp.send("CSS.forcePseudoState", { nodeId, forcedPseudoClasses: ["active"] })
  expect(await eye.evaluate((el) => el.matches(":active"))).toBe(true)  // the test really holds it pressed
  await page.waitForTimeout(500)                                        // the button animates its moves: let any move finish
  expect(await eye.boundingBox()).toEqual(before)
})

test("logins made from the name work from the downloaded sheet, by username or by email", async ({ page, browser, request }) => {
  const api = await staffRequest(request)
  const exam = await examWithOneQuestion(api, "E2E Name Login Exam")
  await loginStaff(page)
  await page.goto(`/admin/exams/${exam.id}?tab=participants`)
  const add = async (text) => {
    await page.getByLabel("Participant names").fill(text)
    await page.getByRole("button", { name: "Create logins" }).click()
    await confirmDialog(page, "Create")
  }

  // a bad email stops the whole list: a clear message, nobody is made
  await add("Zelda Quill\nYara Bad, not-an-email")
  await expect(page.getByText("Line 2: 'not-an-email' is not a valid email")).toBeVisible()
  await expect(page.getByTestId("credentials")).toHaveCount(0)
  expect((await api.get(`/tests/${exam.id}/candidates`)).rows).toHaveLength(0)

  await add("Zelda Quill\nYara Vance, yara.e2e@example.com")
  await expect(page.getByTestId("cred-username")).toHaveCount(2)
  const [zelda, yara] = await page.getByTestId("cred-username").allInnerTexts()
  const [zeldaPw, yaraPw] = await page.getByTestId("cred-password").allInnerTexts()
  expect(zelda).toMatch(/^zelda\d*$/)
  expect(yara).toMatch(/^yara\d*$/)
  expect(zeldaPw).toMatch(/^zel@globx\d{3}$/)
  expect(yaraPw).toMatch(/^yar@globx\d{3}$/)
  await shot(page, "name-logins-sheet")

  // what the file says is what is typed into the login page
  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: /Download all \(2\) as CSV/ }).click()
  const [header, ...lines] = fs.readFileSync(await (await download).path(), "utf8").trim().split(/\r?\n/)
  expect(header).toBe("Name,Username,Password")
  const rows = lines.map((l) => [...l.matchAll(/"((?:[^"]|"")*)"/g)].map((m) => m[1].replace(/""/g, '"')))
  const sheet = Object.fromEntries(rows.map(([name, user, pw]) => [name, { user, pw }]))
  expect(sheet["Zelda Quill"]).toEqual({ user: zelda, pw: zeldaPw })
  expect(sheet["Yara Vance"]).toEqual({ user: yara, pw: yaraPw })

  const signIn = async (who, pw, ok = true) => {
    const w = await candidateWindow(browser)
    await login(w.page, who, pw)
    if (ok) await expect(w.page.getByRole("heading", { name: "Your exams" })).toBeVisible()
    return w
  }
  await (await signIn(sheet["Zelda Quill"].user, sheet["Zelda Quill"].pw)).ctx.close()               // the username
  await (await signIn(sheet["Zelda Quill"].user.toUpperCase(), sheet["Zelda Quill"].pw)).ctx.close() // typed in capitals
  await (await signIn("Yara.E2E@Example.com", sheet["Yara Vance"].pw)).ctx.close()                    // the email, any case
  await (await signIn(sheet["Yara Vance"].user, sheet["Yara Vance"].pw + " ")).ctx.close()            // a space pasted with the password
  const bad = await signIn(sheet["Yara Vance"].user, "wrong-password", false)
  await expect(bad.page.getByText("Invalid email or password")).toBeVisible()
  await bad.ctx.close()
})
