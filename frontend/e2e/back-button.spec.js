import { expect, test } from "@playwright/test"
import { BASE_URL, loginStaff, shot } from "./helpers"

// An in-app Back button in the top bar of every admin screen except the Exams home: nobody needs the browser's Back button.
const nav = (page, name) => page.locator("[data-sidebar=sidebar]").getByText(name, { exact: true })
const back = (page) => page.getByTestId("back-button")

test("Back is in the top bar of every screen but the Exams home, and goes to the screen you came from", async ({ page }) => {
  await loginStaff(page)
  await expect(page).toHaveURL(/\/admin$/)
  await expect(back(page)).toHaveCount(0)                                            // the home screen has nothing behind it

  await nav(page, "Departments").click()                                             // a menu of the sidebar
  await expect(page).toHaveURL(/\/admin\/departments$/)
  await expect(back(page)).toBeVisible()
  await shot(page, "back-button")
  await back(page).click()
  await expect(page).toHaveURL(/\/admin$/)
  await expect(back(page)).toHaveCount(0)

  await page.getByRole("link", { name: "Open" }).first().click()                     // an exam from the list
  await expect(page).toHaveURL(/\/admin\/exams\//)
  await page.getByRole("tab", { name: /Participants/ }).click()                      // tabs inside the exam do not add steps: one Back leaves the exam
  await page.getByRole("tab", { name: /Questions/ }).click()
  await back(page).click()
  await expect(page).toHaveURL(/\/admin$/)

  await nav(page, "Results").click()                                                 // a screen two levels deep: Back goes one level at a time
  await page.getByRole("link", { name: "Open" }).first().click()
  await expect(page).toHaveURL(/\/admin\/results\/[^/]+$/)
  await back(page).click()
  await expect(page).toHaveURL(/\/admin\/results$/)
  await back(page).click()
  await expect(page).toHaveURL(/\/admin$/)
})

test("a screen opened directly (a bookmark or a new tab) still has a Back that goes one level up, inside the app", async ({ page }) => {
  await loginStaff(page)
  const exam = (await page.getByRole("link", { name: "Open" }).first().getAttribute("href"))
  await page.goto(`${BASE_URL}${exam}`)                                              // a fresh load: there is no earlier screen of this visit
  await expect(back(page)).toBeVisible()
  await back(page).click()
  await expect(page).toHaveURL(/\/admin$/)

  await page.goto(`${BASE_URL}/admin/questions`)
  await back(page).click()
  await expect(page).toHaveURL(/\/admin$/)
})

test("Back is there on a phone screen", async ({ browser }) => {
  const ctx = await browser.newContext({ baseURL: BASE_URL, viewport: { width: 390, height: 800 } })
  const page = await ctx.newPage()
  await loginStaff(page)
  await page.goto("/admin/departments")
  await expect(back(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await ctx.close()
})
