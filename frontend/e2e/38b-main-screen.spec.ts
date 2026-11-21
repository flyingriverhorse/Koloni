// Slice 38b in the browser: the canvas fills the main screen, the chat lies over it - one line in its
// bottom left corner closed; open, a column at its left edge as tall as it, as wide as it was dragged
// (0.1.4) - and the canvas keeps the nodes at work clear of it, and of the inspector that slides in beside it.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, freeOfChat, openFreshConversation, settled, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const box = async (target: Locator) => (await target.boundingBox())!
/** How wide the open chat is, in px. */
const across = async (page: Page) => Math.round((await box(chatOf(page))).width)

/** Drags the chat's right edge to `x` px from the stage's left edge (or past the most it may be). */
async function dragTo(page: Page, x: number) {
  const [edge, stage] = [await box(chatOf(page).getByRole('separator', { name: 'Chat width' })), await box(page.locator('.stage'))]
  await page.mouse.move(edge.x + edge.width / 2, edge.y + edge.height / 2)
  await page.mouse.down()
  await page.mouse.move(stage.x + x, edge.y + edge.height / 2, { steps: 6 })
  await page.mouse.up()
}

test('open, the chat is a column at the canvas’s left edge, as tall as it, widened from its right edge between 340 and 760 px (0.1.4), remembered, and a small box again on Esc', async ({ page }) => {
  await openFreshConversation(page)
  const chat = chatOf(page)
  const [stage, open] = [await box(page.locator('.stage')), await box(chat)]
  // At the stage's left edge, from its top to its foot, over the canvas: the canvas has the whole stage.
  expect(Math.round(open.x - stage.x)).toBe(0)
  expect(Math.round(open.y - stage.y)).toBe(0)
  expect(Math.round(stage.y + stage.height - open.y - open.height)).toBe(0)
  expect(await across(page)).toBe(420)
  expect(await box(page.locator('.canvas-flow'))).toEqual(stage)
  const edge = chat.getByRole('separator', { name: 'Chat width' })
  await expect(edge).toHaveAttribute('aria-valuenow', '420')
  // (a stage 1376 px wide: 60% of it is more than 760)
  await expect(edge).toHaveAttribute('aria-valuemax', '760')

  // Dragged past 760 px it stops there, and under 340 px at 340; it is as wide as it was left.
  await dragTo(page, 2000)
  expect(await across(page)).toBe(760)
  await expect(edge).toHaveAttribute('aria-valuenow', '760')
  await dragTo(page, 100)
  expect(await across(page)).toBe(340)
  await dragTo(page, 600)
  expect(await across(page)).toBe(600)
  await page.reload()
  await expect(chat.getByLabel('Message')).toBeVisible()
  expect(await across(page)).toBe(600)
  // From the keyboard: 20 px an arrow.
  await edge.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(edge).toHaveAttribute('aria-valuenow', '580')
  expect(await across(page)).toBe(580)

  // Esc closes it to a small box - its line, and the message box on one line (slice 38e) - with
  // the focus on that line; a click opens it again, as wide.
  await chat.getByLabel('Message').fill('kept as it is')
  await page.keyboard.press('Escape')
  // (hidden, not gone: what was written in it stays)
  await expect(chat.getByRole('tab', { name: 'Chat' })).toBeHidden()
  await expect(chat.getByRole('button', { name: 'Send' })).toBeHidden()
  await expect(chat.getByLabel('Message')).toHaveValue('kept as it is')
  const line = chat.getByRole('button', { name: /^Chat/ })
  await expect(line).toBeFocused()
  await expect(line).toHaveAttribute('aria-expanded', 'false')
  const small = await box(chat)
  expect(Math.round(small.height)).toBeLessThanOrEqual(100)
  // (in its corner, 14 px off the stage's left edge and foot)
  expect(Math.round(small.x - stage.x)).toBe(14)
  expect(Math.round(stage.y + stage.height - small.y - small.height)).toBe(14)
  await line.click()
  await expect(chat.getByLabel('Message')).toBeFocused()
  expect(await across(page)).toBe(580)
  // Its ▾ closes it too; closed, it stays closed after a reload.
  await chat.getByRole('button', { name: 'Hide chat' }).click()
  await page.reload()
  await expect(chat.getByRole('button', { name: /^Chat/ })).toBeVisible()
  await expect(chat.getByRole('tab', { name: 'Chat' })).toBeHidden()
})

test('a card that waits for the user is said on the closed chat’s line, in honey', async ({ page, request }) => {
  const id = await openFreshConversation(page)
  const chat = chatOf(page)
  try {
    await page.getByLabel('Message').fill('edit the greeting')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByRole('button', { name: 'Reject' })).toBeVisible({ timeout: 20_000 })
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    const waits = chat.getByRole('button', { name: /^Chat/ }).getByText('1 waits for you')
    await expect(waits).toBeVisible()
    // the accent of the light theme: what waits is said in honey
    await expect(waits).toHaveCSS('color', 'rgb(146, 90, 13)')
    await chat.getByRole('button', { name: /^Chat/ }).click()
    await chat.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await expect(chat.getByText(/waits? for you/)).toHaveCount(0)
  } finally {
    // Left as it was found: a change still waiting is turned down.
    const conv = id ? await (await request.get(`/api/conversations/${id}`)).json() : { file_changes: [] }
    for (const change of conv.file_changes ?? [])
      if (change.status === 'proposed') await request.post(`/api/file-changes/${change.id}/reject`, { headers: OWN })
  }
})

/** Whether `inner` lies wholly inside `outer`. */
const inside = (inner: { x: number; y: number; width: number; height: number }, outer: typeof inner) =>
  inner.x >= outer.x - 1 && inner.y >= outer.y - 1 && inner.x + inner.width <= outer.x + outer.width + 1 && inner.y + inner.height <= outer.y + outer.height + 1
const apart = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
  a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y

/** Every node at work is on the canvas, clear of the chat; false while none is at work. */
async function workInView(page: Page, nodes: Locator) {
  const [stage, chat] = [await box(page.locator('.canvas-flow')), await box(chatOf(page))]
  const boxes = await Promise.all((await nodes.all()).map(node => node.boundingBox()))
  return boxes.length > 0 && boxes.every(node => node !== null && inside(node, stage) && apart(node, chat))
}

test('while the canvas works, its nodes at work stay in view as the chat grows and the inspector slides in', async ({ page }) => {
  await openFreshConversation(page)
  const running = page.locator('.react-flow__node').filter({ has: page.locator('.node-running') })
  const viewport = page.locator('.react-flow__viewport')
  const zoom = () => viewport.evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)
  // The lead takes a moment before it opens its two reviewers, who take a while each.
  await page.getByLabel('Message').fill('have both files reviewed slowly')
  await page.getByRole('button', { name: 'Send' }).click()
  // The chat is made wider while the turn is at work: new nodes come beside it.
  await dragTo(page, 480)
  expect(await across(page)).toBe(480)
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(3, { timeout: 15_000 })
  await expect(page.getByText(/WORKING · 2 agents/)).toBeVisible()
  await expect.poll(() => workInView(page, running)).toBe(true)

  // A reviewer at work selected: the inspector slides in and the canvas narrows; the zoom stays,
  // and the reviewer stays in view, clear of the chat.
  const drawnAt = await zoom()
  const reviewer = running.filter({ has: page.locator('.node-title', { hasText: /^Reviewer$/ }) })
  await reviewer.locator('.node-title').click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector).toBeVisible()
  await expect.poll(async () => Math.round((await box(page.locator('.canvas-flow'))).width)).toBe(Math.round((await box(page.locator('.stage'))).width))
  // (slid in: it stands right beside the canvas)
  await expect.poll(async () => Math.round((await box(inspector)).x)).toBe(Math.round((await box(page.locator('.stage'))).x + (await box(page.locator('.stage'))).width))
  await expect.poll(() => workInView(page, page.locator('.react-flow__node').filter({ has: page.locator('.node-selected') }))).toBe(true)
  // (Or out by a hair: with the rail's labels (slice 66) the stage is 8px narrower, and the reviewers at work
  // sometimes need that much more room beside the chat - keepWork goes out only as far as that needs.)
  const kept = await zoom()
  expect(kept).toBeLessThanOrEqual(drawnAt + 0.0005)
  // (0.02: on a CI runner, where fonts measure a little wider, keepWork went out by 0.0144.)
  expect(kept).toBeGreaterThan(drawnAt - 0.02)

  // Esc closes it, and the canvas is as wide as it was.
  await inspector.getByRole('button', { name: 'Close inspector' }).focus()
  await page.keyboard.press('Escape')
  await expect(inspector).toHaveCount(0)
  await expect.poll(async () => Math.round((await box(page.locator('.canvas-flow'))).width)).toBe(Math.round((await box(page.locator('.main'))).width))
  await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 20_000 })
})

test('as the inspector slides in and out over work in progress, every node at work stays in view; its Fit View draws the turn beside the chat, not under the inspector; Esc on a node closes it', async ({ page }) => {
  test.setTimeout(60_000)
  await openFreshConversation(page)
  const chat = chatOf(page)
  const running = page.locator('.react-flow__node').filter({ has: page.locator('.node-running') })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // A command that runs half a minute, without asking: the lead and its command are at work.
  await page.getByLabel('Permission level').selectOption('full_auto')
  await page.getByLabel('Message').fill('run slow.py')
  await page.getByRole('button', { name: 'Send' }).click()
  try {
    await dragTo(page, 480)
    await expect(page.locator('.react-flow__node-agent .node-running', { hasText: 'slow.py' })).toHaveCount(1, { timeout: 15_000 })
    await expect.poll(() => workInView(page, running)).toBe(true)

    // The request selected - not at work itself: the inspector slides in, and the nodes at
    // work stay in view with it, clear of the chat.
    const you = page.locator('.react-flow__node-request')
    await you.locator('.node-title').click()
    await expect(inspector).toBeVisible()
    await expect.poll(() => workInView(page, running.or(you))).toBe(true)

    // Fit View with the inspector and the chat open: the selected node is drawn in what the
    // chat leaves free of the narrowed canvas - not under the inspector.
    await page.getByRole('button', { name: 'Fit View' }).click()
    await settled(page)
    expect(inside(await box(you), await freeOfChat(page))).toBe(true)

    // Esc, with the focus on the node that opened it, closes the inspector and leaves the focus there.
    await you.focus()
    await page.keyboard.press('Escape')
    await expect(inspector).toHaveCount(0)
    await expect(you).toBeFocused()
    await expect.poll(() => workInView(page, running)).toBe(true)
  } finally {
    // (Stopped, so that nothing runs on into the next test.)
    if (await chat.getByRole('button', { name: 'Stop' }).isVisible()) await chat.getByRole('button', { name: 'Stop' }).click()
    await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  }
})

// Slice 84d: what an agent does now, on its node - from its own records, never a made-up progress.
for (const theme of ['light', 'dark'] as const) {
  test(`an agent at work says the command it runs and for how long, its dot blinking and its line flowing - still for reduced motion; over, the line says so (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await page.getByLabel('Permission level').selectOption('full_auto')
    await page.getByLabel('Message').fill('run slow.py')
    await page.getByRole('button', { name: 'Send' }).click()
    const lead = page.locator('.react-flow__node-agent')
    const now = lead.locator('.node-now')
    try {
      // the command itself, then how long it has worked (0.1.5: what is cut is the command): the time grows
      await expect(now).toHaveText(/^python -u slow\.py · (<1|\d+)s( · |$)/, { timeout: 15_000 })
      await expect(now).toHaveText(/ · ([2-9]|\d\d)s( · |$)/)
      const moves = () =>
        Promise.all([
          now.locator('.status').evaluate(dot => getComputedStyle(dot, '::before').animationName),
          page.locator('.react-flow__edge.animated .react-flow__edge-path').first().evaluate(path => getComputedStyle(path).animationName),
        ])
      expect(await moves()).toEqual(['pulse', 'dashdraw'])
      expect((await now.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      await settled(page)
      await shot(page, `84d-now-${theme}`)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      expect(await moves()).toEqual(['none', 'none'])
    } finally {
      if (await chat.getByRole('button', { name: 'Stop' }).isVisible()) await chat.getByRole('button', { name: 'Stop' }).click()
      await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
    }
    // over: no blinking, no time, and how it ended
    await expect(now).toHaveCount(0)
    await expect(lead.locator('.node-line')).toHaveText('Stopped')
  })
}
