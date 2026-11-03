import { expect, test } from "@playwright/test"
import { loginStaff, shot } from "./helpers"

test("the sidebar is narrower, its buttons are tall, and the brand lines up with the company name", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await loginStaff(page)
  const sidebar = page.locator("[data-sidebar=sidebar]")
  expect((await sidebar.boundingBox()).width).toBeLessThanOrEqual(230)  // 14rem; it was 16rem (256px)
  expect((await sidebar.boundingBox()).width).toBeGreaterThanOrEqual(200)
  for (const name of ["Exams", "Question bank", "Results"]) {
    expect((await sidebar.getByText(name, { exact: true }).locator("xpath=ancestor-or-self::*[@data-sidebar='menu-button']").boundingBox()).height).toBeGreaterThanOrEqual(44)
  }
  // the brand and the company name sit on one level line: the sidebar's top block is as tall as the top bar
  const [brand, company, topbar] = await Promise.all(["brand", "company", "topbar"].map((id) => page.getByTestId(id).boundingBox()))
  expect(Math.abs(brand.y + brand.height / 2 - (company.y + company.height / 2))).toBeLessThanOrEqual(2)
  expect(Math.abs((await sidebar.locator("[data-sidebar=header]").boundingBox()).height - topbar.height)).toBeLessThanOrEqual(1)
  await expect(page.getByTestId("brand-rule")).toHaveCount(0)  // no dotted line under the brand
  await shot(page, "sidebar")
})

test("a production server without the isolated judge shows a red warning, and a healthy one shows none", async ({ page }) => {
  await loginStaff(page)
  await expect(page.getByTestId("unsafe-judge")).toHaveCount(0)  // the test server runs code through the judge service
  await page.route("**/api/v1/system/sandboxes", (route) =>
    route.fetch().then(async (r) => route.fulfill({ response: r, json: { ...(await r.json()), isolated: false, environment: "production", unsafe_in_production: true } })))
  await page.reload()
  await expect(page.getByTestId("unsafe-judge")).toContainText("isolated judge is not set up")
  await shot(page, "unsafe-judge-warning")
})
