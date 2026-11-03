import { expect, test } from "@playwright/test"
import { loginStaff, shot } from "./helpers"

test("the sidebar is narrower, its buttons are tall, and a dotted line sits under the brand", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await loginStaff(page)
  const sidebar = page.locator("[data-sidebar=sidebar]")
  expect((await sidebar.boundingBox()).width).toBeLessThanOrEqual(230)  // 14rem; it was 16rem (256px)
  expect((await sidebar.boundingBox()).width).toBeGreaterThanOrEqual(200)
  for (const name of ["Exams", "Question bank", "Results"]) {
    expect((await sidebar.getByText(name, { exact: true }).locator("xpath=ancestor-or-self::*[@data-sidebar='menu-button']").boundingBox()).height).toBeGreaterThanOrEqual(44)
  }
  const rule = page.getByTestId("brand-rule")
  expect(await rule.evaluate((el) => getComputedStyle(el).borderBottomStyle)).toBe("dotted")
  const brand = await sidebar.getByText("GLOBX", { exact: false }).first().boundingBox()
  expect((await rule.boundingBox()).y).toBeGreaterThan(brand.y + brand.height)  // below the brand
  await shot(page, "sidebar")
})
