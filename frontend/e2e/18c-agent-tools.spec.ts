import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'
import { MODEL_URL } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// The scripted model server also stands in for the user's own SearXNG (fake-model.mjs): the
// project's search address is the one place on this machine a search may go, so the search
// below is made for real - and nothing leaves the machine.
const SEARX = MODEL_URL

/** Set, or take away, the search address of every project: the specs after this one share the backend. */
async function searchAddress(request: APIRequestContext, url: string) {
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    expect((await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { search_url: url } })).ok()).toBe(true)
  }
}

test.afterEach(async ({ request }) => {
  await searchAddress(request, '')
})

test('a web search asks first, goes out once it is approved, and its row says which way answered', async ({ page, request }) => {
  await openFreshConversation(page)
  await searchAddress(request, SEARX)
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill('search the web for python docs')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Search the web?')).toBeVisible()
  await expect(chat.getByText('python docs', { exact: true })).toBeVisible()
  await expect(chat.getByText('The query leaves this machine.')).toBeVisible()
  await expect(chat.getByRole('button', { name: 'Always allow searching in this conversation' })).toBeVisible()
  await shot(page, '18c-search-asks-first')

  await chat.getByRole('button', { name: 'Search once' }).click()
  await expect(chat.getByText('Found the Python docs.')).toBeVisible()
  await expect(chat.getByText('Search the web?')).toHaveCount(0)
  // The row says what was asked and which way answered; opened, it holds what was found.
  const row = chat.locator('.tool-row').filter({ hasText: 'web_search "python docs"' })
  await expect(row.getByText('answered by SearXNG.')).toBeVisible()
  await row.getByRole('button').click()
  await expect(row.locator('.tool-row-detail')).toContainText('https://docs.python.org/3/')
  await expect(row.locator('.tool-row-detail')).not.toContainText('did not answer')
  // Opened, its detail is under its head, as wide (K-arac-satiri: once beside it, in a narrow column).
  const head = (await row.locator('.tool-row-head').boundingBox())!
  const detail = (await row.locator('.tool-row-detail').boundingBox())!
  expect(detail.y).toBeGreaterThanOrEqual(head.y + head.height - 1)
  expect(Math.abs(detail.x - head.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(detail.width - head.width)).toBeLessThanOrEqual(2)
  await shot(page, '18c-search-answered')
})

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme a search result that reads like orders is given to the agent and warned of, with a False alarm (93-A4)`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await searchAddress(request, SEARX)
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByLabel('Message').fill('search the web for orders')
    await page.getByRole('button', { name: 'Send' }).click()
    await chat.getByRole('button', { name: 'Search once' }).click()
    // Nothing was kept from the agent: it was told to take it as data, and went on.
    await expect(chat.getByText('I took it as data.')).toBeVisible()
    const warned = chat.locator('.injection-warning')
    await expect(warned).toHaveCount(2)
    await expect(warned.first()).toContainText('Text from a web search looks like it tries to give the agent orders (rule: ignore previous).')
    await expect(warned.nth(1)).toContainText('(rule: hide from user)')
    await expect(warned.first()).not.toContainText('Ignore all previous')
    expect((await chat.locator('.msg-group').last().evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(chat, `93a4-warning-${theme}`)
    // Counted by rule (both themes' runs share the backend: the count is one or two).
    await warned.first().getByRole('button', { name: 'False alarm' }).click()
    await expect(warned.first().getByRole('button', { name: 'Marked false alarm' })).toBeDisabled()
    await expect(warned.first()).toContainText(/[12] false alarms? for this rule/)
    await expect(warned.nth(1).getByRole('button', { name: 'False alarm' })).toBeEnabled()
  })

  test(`in the ${theme} theme a Lead's calls in a row are one closed line that counts them, says what failed, and opens to the rows (K-ozet-satiri)`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByLabel('Message').fill('look around, one call a step')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('Looked around.')).toBeVisible({ timeout: 15_000 })

    // Four steps of one call each: one line, closed, before the words.
    const head = chat.getByRole('button', { name: 'Read 1 file, listed 1 folder, searched 1 time, 1 failed, 4 calls, done' })
    await expect(head).toHaveAttribute('aria-expanded', 'false')
    await expect(chat.locator('.tool-run')).toHaveCount(1)
    await expect(chat.locator('.tool-row')).toHaveCount(0)
    await head.click()
    await expect(head).toHaveAttribute('aria-expanded', 'true')
    const rows = chat.locator('.tool-run .tool-row')
    await expect(rows).toHaveCount(4)
    await expect(rows.nth(2)).toContainText('read_file missing.py')
    await expect(rows.nth(2)).toContainText('failed')
    // A row in it opens as ever: what it was given, what came back, under its head.
    await rows.nth(1).getByRole('button').click()
    await expect(rows.nth(1).locator('.tool-row-detail')).toContainText('{"path":"hello.py"}')
    await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
    await shot(chat, `18c-tool-run-${theme}`)
    expect((await chat.locator('.tool-run').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}
