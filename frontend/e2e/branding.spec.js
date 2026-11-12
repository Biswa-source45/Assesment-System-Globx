import { expect, test } from "@playwright/test"
import { loginStaff, newParticipant, shot, startProctoredExam } from "./helpers"

const loaded = (loc) => loc.evaluate((i) => i.complete && i.naturalWidth > 0)  // the picture really arrived
// Neither squeezed nor stretched: the shape on screen is the shape of the file (within 2%).
const keepsShape = (loc) => loc.evaluate((i) => { const r = i.getBoundingClientRect(); return Math.abs(r.width / r.height / (i.naturalWidth / i.naturalHeight) - 1) < 0.02 })

// Compact logo (every screen after sign-in): the K mark and the name, and no "by GLOBX".
async function expectCompact(page, scope = page) {
  const name = scope.getByRole("img", { name: "KAUTILYA", exact: true })
  await expect(name).toBeVisible()
  expect(await loaded(name)).toBe(true)
  expect(await loaded(scope.locator("img").first())).toBe(true)  // the K mark
  expect(await keepsShape(name) && await keepsShape(scope.locator("img").first())).toBe(true)
  const [m, n] = [await scope.locator("img").first().boundingBox(), await name.boundingBox()]
  expect(m.x + m.width).toBeLessThanOrEqual(n.x)  // the mark is left of the name
  expect(Math.abs(m.y + m.height / 2 - (n.y + n.height / 2))).toBeLessThanOrEqual(2)  // on one level line
  await expect(scope.getByRole("img", { name: /GLOBX/ })).toHaveCount(0)
  await expect(page.locator("body")).not.toContainText(/APTIVON|GLOBX Assess/)
}

// Whole logo (sign-in card).
async function expectLogin(page) {
  const logo = page.getByRole("img", { name: /KAUTILYA by GLOBX.*Online Exam Platform/ })
  await expect(logo).toBeVisible()
  expect(await loaded(logo)).toBe(true)
  expect(await keepsShape(logo)).toBe(true)
  const [l, card] = [await logo.boundingBox(), await page.locator("div[data-slot=card]").boundingBox()]
  expect(l.x).toBeGreaterThanOrEqual(card.x)  // the logo stays inside the card
  expect(l.x + l.width).toBeLessThanOrEqual(card.x + card.width)
  await expect(page.getByText("Assess capabilities. Identify excellence.")).toBeVisible()
}

test("sign-in page: logo, tagline, tab title and favicon", async ({ page, request }) => {
  await page.goto("/login")
  await expectLogin(page)
  await expect(page).toHaveTitle(/^KAUTILYA - (Online Exam|Assessment) Platform$/)
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
