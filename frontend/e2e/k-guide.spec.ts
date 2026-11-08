import { expect, test } from '@playwright/test'

// The guide KOLONİ serves at /guide/ (k-learn-more), in a real browser: under its policy
// (app/main.py GUIDE_HEADERS) the theme's pages, styles and search work, and nothing is refused.
test('the guide opens at /guide/ under its policy: pages, search, nothing refused', async ({ page }) => {
  const first = await page.request.get('/guide/')
  // (runtime/site is built by `zensical build`, not by the tests: without it there is no guide to open.)
  test.skip(first.status() === 404 && (await first.text()).includes('not built yet'), 'the guide is not built here')

  const refused: string[] = []
  page.on('console', message => {
    if (/Content Security Policy|Refused to/i.test(message.text())) refused.push(message.text())
  })
  await page.addInitScript(() =>
    document.addEventListener('securitypolicyviolation', event =>
      console.error(`Refused to load ${event.blockedURI} (${event.violatedDirective})`),
    ),
  )

  await page.goto('/guide/')
  await expect(page.locator('h1').first()).toBeVisible()
  await page.goto('/guide/settings/')
  await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible()
  // The theme's stylesheet is applied: its header is laid out, not left as plain text.
  await expect(page.locator('header.md-header')).toHaveCSS('position', 'sticky')

  // Search runs in its worker (worker-src 'self') on search.json (connect-src 'self').
  await page.getByRole('button', { name: /^Search/ }).click()
  await page.keyboard.type('budget')
  const results = page.getByRole('listbox', { name: 'Search results' }).getByRole('option')
  await expect(results.first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('status').filter({ hasText: /\d+ results?/ })).toBeVisible()

  expect(refused).toEqual([])
})
