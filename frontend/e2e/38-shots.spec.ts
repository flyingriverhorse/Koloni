import { expect, test } from './fixtures'
import { OWN, openFreshConversation, openTurns, rail, say, settled, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 38 ("Kovan") changes how the screens look, a part at a time: each part photographs them
// from the code as it was ("before") and as it is, with SHOT_STAGE saying which.
const STAGE = process.env.SHOT_STAGE || 'after'
// Taken on request (KOLONI_SHOTS=1), so an ordinary run does not overwrite the photographs.
test.skip(!process.env.KOLONI_SHOTS, 'screenshots are taken with KOLONI_SHOTS=1')

for (const theme of ['light', 'dark'] as const) {
  test(`shots: the screens slice 38 changes, ${theme}`, async ({ page }) => {
    test.setTimeout(90_000)
    const snap = (name: string) => shot(page, `38a-${name}-${STAGE}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
    await settled(page)
    await snap('main')
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    await expect(page.getByRole('form', { name: 'Project settings' })).toBeVisible()
    await snap('project-settings')
    await page.getByRole('button', { name: 'Close settings' }).click()
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await expect(page.getByRole('button', { name: /^Debugger/ })).toBeVisible()
    await snap('agents')
    await rail(page, 'Usage').click()
    await expect(page.getByRole('heading', { name: 'Usage' })).toBeVisible()
    await snap('usage')
    await rail(page, 'Memory').click()
    await expect(page.getByRole('tabpanel', { name: /^Facts/ })).toBeVisible()
    await snap('memory')
  })
}

// Slice 38b: the main screen. Long names on purpose: a conversation's, and two models' -
// the conversation's (on its button) and the one its turn ran on (on the nodes).
const LONG_TITLE = 'A conversation with a long name about the greeting module and what the reviewer said of it'
for (const theme of ['light', 'dark'] as const) {
  test(`shots: the main screen of slice 38b, ${theme}`, async ({ page }) => {
    test.setTimeout(90_000)
    const snap = (name: string) => shot(page, `38b-${name}-${STAGE}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    const provider = (await (await page.request.get('/api/providers')).json())[0].id
    const choose = (model: string, title?: string) =>
      page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { provider_id: provider, model_id: model, ...(title && { title }) } })
    expect((await choose('Qwen3.8-27B-UD-Q3_K_XL_D3')).ok()).toBe(true)
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
    expect((await choose('claude-haiku-4-5-20251001', LONG_TITLE)).ok()).toBe(true)
    await page.reload()
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
    await expect(page.getByText(LONG_TITLE)).toBeVisible()
    await settled(page)
    await snap('main')
    if (STAGE !== 'after') return
    await page.getByRole('button', { name: 'Hide chat' }).click()
    await settled(page)
    await snap('main-chat-closed')
    await page.getByRole('button', { name: /^Chat\b/ }).click()
    await page.getByRole('button', { name: 'More', exact: true }).click()
    await snap('main-more')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /^Recent/ }).click()
    await expect(page.getByRole('complementary', { name: 'Recent' })).toBeVisible()
    await snap('main-turns')
    await page.keyboard.press('Escape')
    await page.locator('.react-flow__node-agent .node-title').first().click()
    await expect(page.getByRole('complementary', { name: 'Inspector' })).toBeVisible()
    await settled(page)
    await snap('main-inspector')
    // A small window: the long title gives way, the turn's button and the model's name stay whole.
    await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Close inspector' }).click()
    await page.setViewportSize({ width: 1000, height: 560 })
    await settled(page)
    await snap('main-small')
  })
}

// Slice 38c: the list and detail pages - a role that ran with its record table, and the pages
// with nothing on them yet (Tools, Triggers) saying so with their action.
for (const theme of ['light', 'dark'] as const) {
  test(`shots: the list and detail pages of slice 38c, ${theme}`, async ({ page }) => {
    test.setTimeout(90_000)
    const snap = (name: string) => shot(page, `38c-${name}-${STAGE}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('tab', { name: 'History' }).click() // (0.1.0-ui: the page's, its jobs listed)
    await page.getByRole('combobox', { name: 'Role' }).selectOption('Reviewer')
    // Folded, closed (slice 38d): its line says the gist; opened, the table is there.
    const record = page.getByRole('table', { name: 'Record of the last 30 days' })
    await expect(record).toBeHidden()
    await snap('agents-folded')
    await page.locator('.role-record > summary').click()
    await expect(record).toBeVisible()
    await snap('agents')
    // A smaller window: the table scrolls in its own box, the page does not scroll sideways.
    await page.setViewportSize({ width: 1024, height: 768 })
    expect(await page.locator('.agents-page').evaluate(p => p.scrollWidth <= p.clientWidth && document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await snap('agents-1024')
    await page.setViewportSize({ width: 1440, height: 900 })
    await rail(page, 'Models').click()
    await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
    await snap('models')
    await rail(page, 'Tools').click()
    await expect(page.getByRole('heading', { name: 'Tools' })).toBeVisible()
    await snap('tools')
    await rail(page, 'Triggers').click()
    await expect(page.getByRole('heading', { name: 'Triggers' })).toBeVisible()
    await snap('triggers')
  })
}

// Slice 38d: the table pages and Memory - Usage after a turn (and in a smaller window), the
// Board while a turn waits for you, Conversations with a long name, and Memory.
const LONG_NAME = 'A conversation with a long name about the greeting module, what the reviewer said of it and what is left to do'
for (const theme of ['light', 'dark'] as const) {
  test(`shots: the table pages and Memory of slice 38d, ${theme}`, async ({ page }) => {
    test.setTimeout(90_000)
    const snap = (name: string) => shot(page, `38d-${name}-${STAGE}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    expect((await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { title: LONG_NAME } })).ok()).toBe(true)
    await rail(page, 'Usage').click()
    await expect(page.getByRole('table', { name: 'Usage by provider and model' })).toBeVisible()
    await snap('usage')
    // A smaller window: the tables scroll in their own box, the page does not scroll sideways.
    await page.setViewportSize({ width: 1024, height: 768 })
    expect(await page.locator('.memory-page').evaluate(p => p.scrollWidth <= p.clientWidth && document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await snap('usage-1024')
    await page.setViewportSize({ width: 1440, height: 900 })
    await rail(page, 'Canvas').click()
    await page.getByLabel('Message').fill('edit the greeting')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect((await openTurns(page)).locator('.turn-row').getByText('waits for you')).toBeVisible({ timeout: 20_000 })
    await page.keyboard.press('Escape')
    await rail(page, 'Board').click()
    await expect(page.locator('.board-agent .status').filter({ hasText: 'waits for you' }).first()).toBeVisible()
    await snap('board')
    await page.getByRole('button', { name: 'Chats', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible()
    await snap('conversations')
    await rail(page, 'Memory').click()
    await expect(page.getByRole('tabpanel', { name: /^Facts/ })).toBeVisible()
    await snap('memory')
    // The turn that waits is answered, so what runs after finds nothing waiting.
    await rail(page, 'Canvas').click()
    await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
    await expect(page.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })
  })
}
