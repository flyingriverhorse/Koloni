// Slice 38f-1 in the browser: Ctrl+K finds a place and goes there, Esc gives the focus back;
// the first steps follow what is so and go when they are done or hidden; the rail's buttons
// say their names (now under their icons: 66-look); and what is new reads at 4.5 in both themes.
import { expect, test, type Locator, type Page } from './fixtures'
import { contrasts, LINK, openFreshConversation, rail, say, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const palette = (page: Page) => page.getByRole('dialog', { name: 'Go to' })
const steps = (page: Page) => page.getByRole('region', { name: 'First steps' })

test('Ctrl+K from the message box: it filters as it is typed, the arrows and Enter go there, Esc gives the focus back', async ({ page }) => {
  await openFreshConversation(page)
  const box = page.getByRole('region', { name: 'Chat' }).getByLabel('Message')
  await box.click()
  await page.keyboard.press('Control+k')
  const find = palette(page).getByRole('combobox', { name: 'Go to' })
  await expect(find).toBeFocused()
  await expect(box).toHaveValue('')
  await find.fill('memo')
  const options = palette(page).getByRole('option')
  await expect(options.first()).toHaveText(/^Memory/)
  await expect(options.last()).toHaveText(/^Search in messages: “memo”/)
  await expect(options.first()).toHaveAttribute('aria-selected', 'true')
  // round the top: the last row, "Search in messages"; and back
  await page.keyboard.press('ArrowUp')
  await expect(options.last()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('ArrowDown')
  await expect(options.first()).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('Escape')
  await expect(palette(page)).toHaveCount(0)
  await expect(box).toBeFocused()
  // Esc in the palette is the palette's: the chat stays open
  await expect(page.getByRole('region', { name: 'Chat' }).getByRole('tab', { name: 'Chat' })).toBeVisible()

  await page.keyboard.press('Control+k')
  await palette(page).getByRole('combobox').fill('memory')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Memory', exact: true })).toBeVisible()
  await expect(rail(page, 'Memory')).toHaveAttribute('aria-pressed', 'true')

  // "Search in messages": the memory's search, with the words, searched
  await page.keyboard.press('Control+k')
  await palette(page).getByRole('combobox').fill('greeting')
  const searched = page.waitForResponse(r => r.url().includes('/memory/search?q=greeting'))
  await palette(page).getByRole('option', { name: /Search in messages/ }).click()
  await searched
  const search = page.getByLabel('Search everything this project remembers')
  await expect(search).toHaveValue('greeting')
  await expect(search).toBeFocused()
})

test('on an empty install the first steps are one path - a provider, a folder, a message - and the current one goes where it is done', async ({ page }) => {
  // (This install has folders and chats from the other specs: the page is told it has none, and that its provider - as
  // "Local", made at the first start - does not answer: a seeded provider with no model server behind it is not done.)
  const empty = ['/api/providers', '/api/projects', '/api/conversations']
  await page.route(url => empty.includes(url.pathname), route => (route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.fallback()))
  await page.route(url => url.pathname === '/api/health', async route => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), provider_name: 'Local', model_reachable: false, error: 'model server unreachable: refused' } })
  })
  await page.goto(LINK)
  const items = steps(page).getByRole('listitem')
  await expect(items).toHaveCount(3)
  await expect(items.nth(0)).toHaveAttribute('aria-current', 'step')
  await expect(steps(page).locator('[aria-current]')).toHaveCount(1)
  await expect(steps(page).getByText(/^To do:/)).toHaveCount(3)
  await expect(items.nth(0)).toContainText("Local isn't answering - add another provider, or start its model server.")
  // only the card takes a click: the canvas around it is the canvas's
  const card = (await steps(page).boundingBox())!
  const stage = (await page.locator('.canvas-flow').boundingBox())!
  expect(card.width).toBeLessThan(stage.width / 2)
  // the current step and the ones after it read at 4.5 or more too
  expect((await steps(page).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  if (process.env.KOLONI_SHOTS) await shot(page, '38f1-first-steps')
  // the current step alone has a button: the Models page, on its form for a new provider
  await expect(steps(page).getByRole('button')).toHaveText(['Add a provider', 'Hide the first steps'])
  await steps(page).getByRole('button', { name: 'Add a provider' }).click()
  await expect(page.getByRole('dialog', { name: 'Add a provider' })).toBeVisible()
})

test('the first steps go once a message is written, and come back from Help, all three done, until hidden', async ({ page, request }) => {
  await openFreshConversation(page)
  const health = await (await request.get('/api/health')).json()
  test.skip(!health.model_reachable || health.not_listed, 'the default provider does not answer here: no message can be written')
  const box = page.getByRole('region', { name: 'Chat' }).getByLabel('Message')
  await say(page, 'hello', 'Hello! Ask me to read or change a file.')
  await expect(steps(page)).toHaveCount(0)
  // gone by what is so - in a new, empty chat too
  await openFreshConversation(page)
  await expect(box).toBeVisible()
  await expect(steps(page)).toHaveCount(0)

  // Help brings them back, all three done; Hide puts them away again, for good
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  await page.getByRole('dialog', { name: 'Help' }).getByRole('button', { name: 'Show the first steps' }).click()
  await expect(steps(page).getByText(/^Done:/)).toHaveCount(3)
  await steps(page).getByRole('button', { name: 'Hide the first steps' }).click()
  await expect(steps(page)).toHaveCount(0)
  await page.reload()
  await expect(box).toBeVisible()
  await expect(steps(page)).toHaveCount(0)
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme what slice 38f-1 added reads at 4.5 or more, a chosen row too`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const check = async (root: Locator, least: number) => {
      const pieces = await root.evaluate(contrasts)
      expect(pieces.length).toBeGreaterThanOrEqual(least)
      expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    }
    // (shown again from Help, whatever an earlier test left)
    await page.getByRole('button', { name: 'Help', exact: true }).click()
    const help = page.getByRole('dialog', { name: 'Help' })
    await check(help, 10)
    if (process.env.KOLONI_SHOTS) await shot(page, `38f1-help-${theme}`)
    await help.getByRole('button', { name: 'Show the first steps' }).click()
    await check(steps(page), 4)

    await page.getByRole('button', { name: 'Canvas legend' }).click()
    const legend = page.getByRole('dialog', { name: 'Canvas legend' })
    await check(legend, 20)
    if (process.env.KOLONI_SHOTS) await shot(page, `38f1-legend-${theme}`)
    await page.keyboard.press('Escape')
    await expect(legend).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Canvas legend' })).toBeFocused()

    await page.keyboard.press('Control+k')
    await palette(page).getByRole('combobox').fill('s')
    // the first row is the chosen one: it reads on its honey ground
    await expect(palette(page).getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
    await check(palette(page), 6)
    if (process.env.KOLONI_SHOTS) await shot(page, `38f1-palette-${theme}`)
  })
