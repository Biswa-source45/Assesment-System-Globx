import { expect, test } from "@playwright/test"
import { loginStaff, newParticipant, shot, startProctoredExam } from "./helpers"

const loaded = (loc) => loc.evaluate((i) => i.complete && i.naturalWidth > 0)  // the picture really arrived

// Compact logo (headers): AV mark, the name, and "by GLOBX" under the name, a little to the right.
async function expectCompact(page, scope = page) {
  const name = scope.getByRole("img", { name: "APTIVON", exact: true })
  const by = scope.getByRole("img", { name: "by GLOBX", exact: true })
  await expect(name).toBeVisible()
  await expect(by).toBeVisible()
  expect(await loaded(name)).toBe(true)
  expect(await loaded(by)).toBe(true)
  expect(await loaded(scope.locator("img").first())).toBe(true)  // the AV mark
  const [n, b] = [await name.boundingBox(), await by.boundingBox()]
  expect(b.y).toBeGreaterThanOrEqual(n.y + n.height - 1)  // under the name
  expect(b.x).toBeGreaterThan(n.x)  // with its own small margin
  expect(b.height).toBeLessThanOrEqual(n.height / 1.5)  // and much smaller
  await expect(page.locator("body")).not.toContainText("GLOBX Assess")
}

// Whole logo (sign-in card).
async function expectLogin(page) {
  const logo = page.getByRole("img", { name: /APTIVON by GLOBX.*Enterprise Assessment Platform/ })
  await expect(logo).toBeVisible()
  expect(await loaded(logo)).toBe(true)
  await expect(page.getByText("Assess capabilities. Identify excellence.")).toBeVisible()
}

test("sign-in page: logo, tagline, tab title and favicon", async ({ page, request }) => {
  await page.goto("/login")
  await expectLogin(page)
  await expect(page).toHaveTitle(/APTIVON.*Assessment Platform/)
  for (const rel of ["icon", "apple-touch-icon"]) {
    const res = await request.get(await page.locator(`link[rel=${rel}]`).getAttribute("href"))
    expect(res.status()).toBe(200)
    expect(res.headers()["content-type"]).toContain("image/png")
  }
  await shot(page, "brand-login")
})

test("sign-in page on a phone has no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 700 })
  await page.goto("/login")
  await expectLogin(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test("the admin sidebar shows it", async ({ page }) => {
  await loginStaff(page)
  await expectCompact(page, page.getByTestId("brand"))
  await shot(page, "brand-sidebar")
})

test("the candidate home and the exam screen show it", async ({ page, request }) => {
  const p = await newParticipant(request, "Brand Check")
  await startProctoredExam(page, p.username, undefined, p.password)
  await expectCompact(page, page.locator("header"))
  await shot(page, "brand-exam-header")
  await page.goto("/exam")
  await expect(page.getByRole("heading", { name: "Your exams" })).toBeVisible()
  await expectCompact(page, page.locator("header"))
})
