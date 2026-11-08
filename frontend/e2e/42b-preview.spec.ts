// Slice 42b in the browser: an agent starts a dev server that keeps running. It is asked for (the
// card says it keeps running), the address it prints is taken, and under Preview its page is live
// beside the chat - its script runs, in its own origin. Stop ends it with what it started; a
// server that refuses a frame is offered in the browser instead. A page an agent shows is previewed in Workspace.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const viewOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })

/** Left as it was found: whatever still serves is stopped. */
async function stopServing(page: Page, id: string) {
  if (!id) return
  const conv = await (await page.request.get(`/api/conversations/${id}`)).json()
  for (const command of conv.commands ?? [])
    if (command.status === 'running') await page.request.post(`/api/commands/${command.id}/stop`, { headers: OWN })
}

async function start(page: Page, words: string) {
  const chat = chatOf(page)
  await page.getByLabel('Message').fill(words)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByText('keeps running, serves a page')).toBeVisible()
  // (no rule covers a server: it is asked every time)
  await expect(chat.getByRole('button', { name: /^Always run/ })).toHaveCount(0)
  await chat.getByRole('button', { name: 'Run once' }).click()
  await expect(chat.getByText('The site is up.')).toBeVisible({ timeout: 20_000 })
}

async function check(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

test('a dev server is asked for, keeps running after the turn, is shown live under Preview, and Stop ends it with what it started', async ({ page }) => {
  test.setTimeout(90_000)
  const id = await openFreshConversation(page)
  try {
    await start(page, 'start the site')
    // (no Preview button: Workspace opens by itself on it, once its address is known)
    await expect(page.getByRole('button', { name: /^Preview/ })).toHaveCount(0)
    const view = viewOf(page)
    await expect(view).toBeVisible({ timeout: 15_000 })
    await expect(view.getByRole('tree', { name: 'Files' }).getByRole('treeitem').first()).toHaveText('Previews')
    const frame = view.locator('iframe')
    await expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms')
    const address = (await frame.getAttribute('src')) ?? ''
    expect(address).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/$/)
    // its own page, its script run: in its own origin, not the app's
    await expect(page.frameLocator('.view-panel iframe').getByText('Served live')).toBeVisible()
    await expect(view.getByRole('status')).toHaveText('running')
    const open = view.getByRole('link', { name: 'Open in browser' })
    await expect(open).toHaveAttribute('href', address)
    await expect(open).toHaveAttribute('rel', 'noopener noreferrer')
    if (process.env.KOLONI_SHOTS) await shot(page, '42b-preview')
    await view.getByRole('button', { name: 'Reload' }).click()
    await expect(page.frameLocator('.view-panel iframe').getByText('Served live')).toBeVisible()

    await view.getByRole('button', { name: 'Stop' }).click()
    await expect(view.getByRole('status')).toHaveText('stopped')
    await expect(view.getByText('It is not running any more.')).toBeVisible()
    // stopped means gone: nothing answers at its address any more
    await expect.poll(() => page.request.get(address, { timeout: 2000 }).then(() => 'answered', () => 'gone')).toBe('gone')
  } finally {
    await stopServing(page, id)
  }
})

test('a server that refuses to be framed is not framed: it is offered in the browser', async ({ page }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page)
  try {
    await start(page, 'start the guarded site')
    const view = viewOf(page)
    await expect(view.getByText('This server does not allow being shown here.')).toBeVisible({ timeout: 15_000 })
    await expect(view.locator('iframe')).toHaveCount(0)
    await expect(view.getByRole('link', { name: 'Open in browser' })).toHaveCount(2)
    if (process.env.KOLONI_SHOTS) await shot(view, '42b-refused')
  } finally {
    await stopServing(page, id)
  }
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme the Preview window's header, tree and words stand out (contrast 4.5 or more)`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    try {
      await start(page, 'start the guarded site')
      const view = viewOf(page)
      await expect(view.getByText('This server does not allow being shown here.')).toBeVisible({ timeout: 15_000 })
      await check(view.locator('.view-where'), 3)
      await check(view.getByRole('tree', { name: 'Files' }), 2)
      await check(view.locator('.view-body'), 2)
      // (the chat's: a file, with a number only when something waits)
      await check(page.getByRole('button', { name: /^Workspace/ }), 0)
      if (process.env.KOLONI_SHOTS) await shot(page, `42b-preview-${theme}`)
    } finally {
      await stopServing(page, id)
    }
  })

test('a page an agent shows is previewed in Workspace, by its sandbox and Run once', async ({ page }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('show the game')
  await page.getByRole('button', { name: 'Send' }).click()
  // (opened by itself on it, its folder opened)
  const view = viewOf(page)
  await expect(view.getByRole('tab', { name: 'index.html' })).toHaveAttribute('aria-selected', 'true', { timeout: 20_000 })
  await expect(view.getByRole('treeitem', { name: 'game42' })).toHaveAttribute('aria-expanded', 'true')
  await expect(view.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', '')
  await view.getByRole('button', { name: 'Run once' }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(page.frameLocator('.view-panel iframe').getByText('A game')).toBeVisible()
  await expect(view.locator('iframe')).toHaveAttribute('src', /\/api\/(conversations|projects)\/.+\/index\.html/)
})

test('K-39-betik: a page’s script is asked about - Run once, Always run in this chat, Don’t run; always, the next page of the chat runs unasked', async ({ page }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('show the game')
  await page.getByRole('button', { name: 'Send' }).click()
  const view = viewOf(page)
  await expect(view.getByRole('tab', { name: 'index.html' })).toHaveAttribute('aria-selected', 'true', { timeout: 20_000 })
  const ask = view.getByRole('group', { name: 'Run its script?' })
  await expect(ask.getByRole('button')).toHaveText(['Run once', 'Always run in this chat', 'Don’t run'])
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', '')
  await shot(view, 'k39-script-ask-light')
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await shot(view, 'k39-script-ask-dark')
  await page.evaluate(() => document.documentElement.classList.remove('dark'))

  // Always: it runs, and so does the page opened again after a reload - nothing asked.
  await ask.getByRole('button', { name: 'Always run in this chat' }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(view.getByRole('group', { name: 'Its script' })).toContainText('Scripts run in this chat without asking.')
  await page.reload()
  await page.getByRole('button', { name: /^Workspace/ }).first().click()
  await view.getByRole('treeitem', { name: /^index\.html/ }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(view.getByRole('group', { name: 'Run its script?' })).toHaveCount(0)

  // Asked each time again, from the same place; Don't run leaves the page drawn without its script.
  await view.getByRole('group', { name: 'Its script' }).getByRole('button', { name: 'Ask each time' }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', '')
  await view.getByRole('group', { name: 'Run its script?' }).getByRole('button', { name: 'Don’t run' }).click()
  await expect(view.getByRole('group', { name: 'Run its script?' })).toHaveCount(0)
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', '')

  // B-168: a slim line says it did not run, and Run once is still there; ran once, Ask each time takes it back.
  const said = view.getByRole('group', { name: 'Its script' })
  await expect(said).toContainText('Script not run.')
  await said.getByRole('button', { name: 'Run once' }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
  await expect(said).toContainText('Script ran once.')
  await said.getByRole('button', { name: 'Ask each time' }).click()
  await expect(view.locator('iframe')).toHaveAttribute('sandbox', '')
  await expect(view.getByRole('group', { name: 'Run its script?' }).getByRole('button')).toHaveText(['Run once', 'Always run in this chat', 'Don’t run'])
})
