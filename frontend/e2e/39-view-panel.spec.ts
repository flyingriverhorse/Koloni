// Slice 39 in the browser, in the Workspace window of 42c: what an agent writes to be seen - a page,
// while its change still waits - comes up beside the chat, its script running in a frame that
// reaches neither the app nor the window it is in, and is drawn anew when the agent writes it
// again; a picture the agent shows comes up there too. Esc closes the window, back on its button;
// it expands over the canvas.
import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, settled, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const panelOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })
/** The Workspace button: at the open chat's foot, or beside the small box (slice 42d). */
const filesOf = (page: Page) => page.getByRole('button', { name: /^Workspace/ })
const frameOf = (page: Page) => page.frameLocator('.view-panel iframe')

/** Every piece of text in it against what it stands on: 4.5 or more. */
async function check(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

/** Left as it was found: a change still waiting is turned down. */
async function rejectWaiting(page: Page, id: string) {
  if (!id) return
  const conv = await (await page.request.get(`/api/conversations/${id}`)).json()
  for (const change of conv.file_changes ?? [])
    if (change.status === 'proposed') await page.request.post(`/api/file-changes/${change.id}/reject`, { headers: OWN })
}

test('a page an agent writes is drawn beside the chat - while it waits, as it will be - runs its script once asked to, reaches nothing, and is drawn anew when written again', async ({ page }) => {
  test.setTimeout(90_000)
  // A page not there yet: kept by an earlier run of this test, the same write would change nothing.
  rmSync(path.join(PROJECT_DIR, 'view39.html'), { force: true })
  const id = await openFreshConversation(page)
  const chat = chatOf(page)
  try {
    await page.getByLabel('Message').fill('make a view page')
    await page.getByRole('button', { name: 'Send' }).click()
    // Not kept yet: it waits for the user, and can be looked at before - Workspace opens on it, its diff first.
    await expect(chat.getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 20_000 })
    const panel = panelOf(page)
    await expect(panel).toBeVisible()
    await expect(panel.getByRole('tab', { name: 'view39.html' })).toHaveAttribute('aria-selected', 'true')
    await expect(panel.locator('.view-where')).toContainText('view39.html · Lead')
    await expect(panel.locator('.changes-info')).toContainText('Waits for you')
    await expect(panel.getByRole('button', { name: 'Diff' })).toHaveAttribute('aria-pressed', 'true')
    await panel.getByRole('button', { name: 'Preview' }).click()
    const app = page.url()

    // Drawn, and nothing of it run: not until the user asks for it.
    const frame = frameOf(page)
    await expect(frame.locator('h1')).toHaveText('A page an agent wrote')
    await expect(panel.locator('iframe')).toHaveAttribute('sandbox', '')
    await expect(frame.locator('#said')).toHaveText('not run')
    await check(panel, 2)
    await panel.getByRole('button', { name: 'Run once' }).click()
    await expect(panel.getByRole('button', { name: 'Run once' })).toHaveCount(0)

    // Its script ran; it could neither fetch from the app, nor read its cookies, nor move the window it is in.
    await expect(frame.locator('#said')).toHaveText('ran: one')
    // What it names beside itself comes from beside it.
    await expect(frame.locator('#pic')).toHaveText('picture: came')
    await expect(frame.locator('#api')).toHaveText('fetch: blocked')
    await expect(frame.locator('#out')).toHaveText('outside: blocked')
    await expect(frame.locator('#cookie')).toHaveText('cookie: refused')
    await expect(frame.locator('#top')).toHaveText('top: refused')
    expect(page.url()).toBe(app)
    // The frame is the sandbox the server's policy says too: scripts, and an origin of its own.
    await expect(panel.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts')
    expect(await frame.locator('body').evaluate(() => window.origin)).toBe('null')

    // Expanded over the canvas, and back.
    await panel.getByRole('button', { name: 'Expand workspace' }).click()
    await panel.getByRole('button', { name: 'Shrink workspace' }).click()
    await expect(panel.getByRole('button', { name: 'Expand workspace' })).toBeVisible()

    // Kept, and written again: the panel, still open, draws the new one.
    await chat.getByRole('button', { name: 'Approve' }).click()
    await expect(chat.getByText('The page is written.')).toBeVisible({ timeout: 20_000 })
    await expect(panel.locator('.changes-info')).toContainText('Applied')
    await page.getByLabel('Message').fill('change the view page')
    await page.getByRole('button', { name: 'Send' }).click()
    // (run once, it runs again as written again: not asked a second time)
    await expect(frame.locator('#said')).toHaveText('ran: two', { timeout: 20_000 })
    await expect(panel.locator('.changes-info')).toContainText('Waits for you')
    expect(page.url()).toBe(app)
    await chat.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText(/The page was not written/)).toBeVisible({ timeout: 20_000 })
    // Turned down, the second is gone from the list; the first, kept, is what is shown.
    await expect(frame.locator('#said')).toHaveText('ran: one', { timeout: 10_000 })
  } finally {
    await rejectWaiting(page, id)
  }
})

test('a picture an agent shows opens Workspace by itself, the focus left in the message box; Esc closes the window back on its button; it expands over the canvas and shrinks again', async ({ page }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  const chat = chatOf(page)
  await page.getByLabel('Message').fill('show the chart')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
  const button = filesOf(page)
  const panel = panelOf(page)
  const picture = panel.getByRole('img', { name: 'chart39.png' })
  await expect(picture).toBeVisible({ timeout: 10_000 })
  await expect(panel.locator(':focus')).toHaveCount(0)
  expect(await picture.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(240)
  await expect(panel).toContainText('the chart, as a picture')
  await expect(panel.locator('.view-where')).toContainText('chart39.png · Lead')
  // (opened, it is seen)
  await expect(button).not.toHaveAccessibleName(/ new$/)

  // Beside the open chat and as tall, half the
  // canvas wide; over the canvas, not the chat.
  const [stage, box, chatBox] = [(await page.locator('.stage').boundingBox())!, (await panel.boundingBox())!, (await chat.boundingBox())!]
  expect(box.x).toBeGreaterThanOrEqual(chatBox.x + chatBox.width)
  expect(Math.round(box.y)).toBe(Math.round(chatBox.y))
  expect(Math.round(box.y + box.height)).toBe(Math.round(chatBox.y + chatBox.height))
  expect(Math.round(box.width)).toBe(Math.round(stage.width / 2))

  // Expanded, it lies over all of the canvas; shrunk, beside the chat again.
  await panel.getByRole('button', { name: 'Expand workspace' }).click()
  const wide = (await panel.boundingBox())!
  expect(Math.round(wide.width)).toBe(Math.round(stage.width - 28))
  expect(Math.round(wide.height)).toBe(Math.round(stage.height - 28))
  await panel.getByRole('button', { name: 'Shrink workspace' }).click()
  expect(Math.round((await panel.boundingBox())!.width)).toBe(Math.round(stage.width / 2))

  // Esc closes it, and the focus is on what opened it.
  await panel.getByRole('tab', { name: 'chart39.png' }).focus()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(button).toBeFocused()
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  // (the chat stays open)
  await expect(chat.getByLabel('Message')).toBeVisible()

  // On a canvas too narrow for both side by side, it is still a panel to read: over the chat, inside the canvas.
  await page.setViewportSize({ width: 700, height: 900 })
  await button.click()
  const [narrow, inStage] = [(await panel.boundingBox())!, (await page.locator('.stage').boundingBox())!]
  expect(narrow.width).toBeGreaterThanOrEqual(279)
  expect(narrow.x + narrow.width).toBeLessThanOrEqual(inStage.x + inStage.width - 13)
})

/** Whether `a` and `b` do not overlap; and whether `inner` lies wholly inside `outer`. */
type Box = { x: number; y: number; width: number; height: number }
const apart = (a: Box, b: Box) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y
const inside = (inner: Box, outer: Box) =>
  inner.x >= outer.x - 1 && inner.y >= outer.y - 1 && inner.x + inner.width <= outer.x + outer.width + 1 && inner.y + inner.height <= outer.y + outer.height + 1

test('with the panel open, the nodes at work stay on the canvas, clear of it and of the chat', async ({ page }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  const chat = chatOf(page)
  await page.getByLabel('Message').fill('show the chart')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
  // (opened by itself on the chart)
  const panel = panelOf(page)
  await expect(panel).toBeVisible({ timeout: 10_000 })
  // A command that runs half a minute, without asking: the lead and its command are at work.
  await page.getByLabel('Permission level').selectOption('full_auto')
  await page.getByLabel('Message').fill('run slow.py')
  await page.getByRole('button', { name: 'Send' }).click()
  try {
    const running = page.locator('.react-flow__node').filter({ has: page.locator('.node-running') })
    await expect(page.locator('.react-flow__node-agent .node-running', { hasText: 'slow.py' })).toHaveCount(1, { timeout: 15_000 })
    await expect
      .poll(async () => {
        const [stage, over, beside] = [(await page.locator('.canvas-flow').boundingBox())!, (await panel.boundingBox())!, (await chat.boundingBox())!]
        const nodes = await Promise.all((await running.all()).map(node => node.boundingBox()))
        return nodes.length > 0 && nodes.every(node => node !== null && inside(node, stage) && apart(node, over) && apart(node, beside))
      })
      .toBe(true)
  } finally {
    // (Stopped, so that nothing runs on into the next test.)
    if (await chat.getByRole('button', { name: 'Stop' }).isVisible()) await chat.getByRole('button', { name: 'Stop' }).click()
    await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  }
})

test('a page that goes elsewhere by itself once its script runs is taken off the panel, and the user told', async ({ page }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page)
  const chat = chatOf(page)
  try {
    await page.getByLabel('Message').fill('make a moving page')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 20_000 })
    // (Workspace opens on it, as it waits: its diff first)
    const panel = panelOf(page)
    await panel.getByRole('button', { name: 'Preview' }).click()
    // Drawn without its script, it stays where it is.
    await expect(frameOf(page).locator('p')).toHaveText('Here a moment.')
    const app = page.url()
    await panel.getByRole('button', { name: 'Run once' }).click()
    await expect(panel.getByText('The page tried to go elsewhere; it was stopped.')).toBeVisible()
    await expect(panel.locator('iframe')).toHaveCount(0)
    expect(page.url()).toBe(app)
  } finally {
    await rejectWaiting(page, id)
  }
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme every text of the view panel and its button stands out from what it is on (contrast 4.5 or more)`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    const chat = chatOf(page)
    await page.getByLabel('Message').fill('show the chart')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
    // (opened by itself on it)
    await expect(panelOf(page).getByRole('img', { name: 'chart39.png' })).toBeVisible({ timeout: 10_000 })
    // (the chat's: a file, with a number only when something waits)
    await check(filesOf(page), 0)
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await check(page.locator('.chat-dock').getByRole('button', { name: /^Workspace/ }), 2)
    await check(chat.getByRole('button', { name: /^Chat/ }), 3)
    await chat.getByRole('button', { name: /^Chat/ }).click()
    // (its tab among them)
    await check(panelOf(page), 3)
    // and with a page that waits to be run: its ask to run it too
    try {
      // (the version the first test left unwritten: a change whichever ran before)
      await page.getByLabel('Message').fill('change the view page')
      await page.getByRole('button', { name: 'Send' }).click()
      await panelOf(page).getByRole('tab', { name: 'view39.html' }).waitFor({ timeout: 20_000 })
      await panelOf(page).getByRole('button', { name: 'Preview' }).click()
      await expect(panelOf(page).getByRole('button', { name: 'Run once' })).toBeVisible({ timeout: 20_000 })
      await check(panelOf(page).locator('.view-where').first(), 2)
      await check(panelOf(page).getByRole('group', { name: 'Run its script?' }), 4)
      await check(panelOf(page).getByRole('tablist', { name: 'Open files' }), 1)
    } finally {
      await rejectWaiting(page, id)
    }
  })

// Taken on request (KOLONI_SHOTS=1), like slice 38's: runtime/shots/39-*.png.
for (const theme of ['light', 'dark'] as const)
  test(`shots: the view panel of slice 39, ${theme}`, async ({ page }) => {
    test.skip(!process.env.KOLONI_SHOTS, 'screenshots are taken with KOLONI_SHOTS=1')
    test.setTimeout(90_000)
    const snap = (name: string) => shot(page, `39-${name}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    const chat = chatOf(page)
    try {
      // (the version the first test left unwritten: a change whichever ran before)
      await page.getByLabel('Message').fill('change the view page')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByRole('button', { name: 'Approve' })).toBeVisible({ timeout: 20_000 })
      await settled(page)
      await snap('diff')
      await panelOf(page).getByRole('button', { name: 'Preview' }).click()
      await expect(frameOf(page).locator('#said')).toHaveText('not run')
      await settled(page)
      await snap('page-not-run')
      await panelOf(page).getByRole('button', { name: 'Run once' }).click()
      await expect(frameOf(page).locator('#api')).toHaveText('fetch: blocked')
      await snap('page')
      await panelOf(page).getByRole('button', { name: 'Expand workspace' }).click()
      await snap('page-wide')
      await panelOf(page).getByRole('button', { name: 'Shrink workspace' }).click()
      await chat.getByRole('button', { name: 'Reject' }).click()
      await expect(chat.getByText(/The page was not written/)).toBeVisible({ timeout: 20_000 })
      await page.getByLabel('Message').fill('show the chart')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
      await panelOf(page).getByRole('treeitem', { name: /^chart39\.png/ }).click()
      await expect(panelOf(page).getByRole('img', { name: 'chart39.png' })).toBeVisible()
      await settled(page)
      await snap('picture')
    } finally {
      await rejectWaiting(page, id)
    }
  })
