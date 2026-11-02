import { expect, test } from "@playwright/test"
import { login, loginCandidate, shot } from "./helpers"

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
      await page.locator(".cm-content").click()
      await page.keyboard.press("Control+A")
      await page.keyboard.type("a,b=map(int,input().split())\nprint(a+b)")
      await page.getByRole("button", { name: "Run on samples" }).click()
      await expect(page.getByTestId("code-results").getByText("AC").first()).toBeVisible({ timeout: 30_000 })
      await page.getByRole("button", { name: "Submit", exact: true }).click()
      await expect(page.getByText(/Score \d+(\.\d+)? \/ \d+(\.\d+)?/)).toBeVisible({ timeout: 60_000 })
      await shot(page, "exam-code-result")
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

test("code that fails a sample case is reported, not hidden", async ({ page }) => {
  await loginCandidate(page, "amit")
  await page.locator("div[data-slot=card]").filter({ hasText: "Practice Test" }).getByRole("link", { name: /Start|Resume/ }).click()
  await page.getByRole("button", { name: "Start exam" }).click()
  const palette = page.getByLabel("Question palette").getByRole("button")
  for (let i = 0; i < 3; i++) {
    await palette.nth(i).click()
    if (await page.locator(".cm-content").count()) break
  }
  await page.locator(".cm-content").click()
  await page.keyboard.press("Control+A")
  await page.keyboard.type("print(0)")
  await page.getByRole("button", { name: "Run on samples" }).click()
  await expect(page.getByTestId("code-results").getByText("WA").first()).toBeVisible({ timeout: 30_000 })
})
