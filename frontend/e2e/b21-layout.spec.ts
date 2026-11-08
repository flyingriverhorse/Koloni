import { expect, test } from './fixtures'
import { openFreshConversation } from './helpers'

// B-130 (live): on a narrow window the New role form was drawn over the teams list, the teams' lead switches on its
// fields - the teams' own `flex: 1` left them 44px high in the page's column.
test('on a narrow window the teams list and the New role form lie one under the other', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 })
  await openFreshConversation(page)
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await page.getByRole('button', { name: 'New role' }).click()
  const [teams, form] = [await page.locator('.agents-teams').boundingBox(), await page.locator('.role-panel').boundingBox()]
  expect(form!.y).toBeGreaterThanOrEqual(teams!.y + teams!.height - 1)
  const switches = await page.locator('.agents-teams .switch, .agents-teams input[type=checkbox]').evaluateAll(all => all.map(one => one.getBoundingClientRect().bottom))
  expect(Math.max(...switches)).toBeLessThanOrEqual(form!.y + 1)
})

// 0.1.0-ui: on a small screen the roles are not up and down away - "Roles ▸ N" stays at the top while the page scrolls.
test('on a narrow window "Roles ▸ N" stays at the top of the page as it scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 700 })
  await openFreshConversation(page)
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await page.getByRole('button', { name: 'New role' }).click() // (the form under the teams: a page to scroll)
  const scroller = page.locator('.agents-page')
  // (Scrolled again till it goes: the page is tall enough only once the form and the teams' list are drawn.)
  await expect.poll(() => scroller.evaluate(one => (one.scrollTo(0, 800), one.scrollTop))).toBeGreaterThan(300)
  const [toggle, top] = [await page.getByRole('button', { name: /^Roles ▸/ }).boundingBox(), await scroller.boundingBox()]
  expect(Math.abs(toggle!.y - top!.y)).toBeLessThan(24)
})
