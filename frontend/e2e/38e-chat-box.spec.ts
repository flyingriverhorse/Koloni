// Slice 38e in the browser: the chat as the reference has it - a small box to type in while
// closed, Workspace beside it - and its window and the Workspace window dragged anywhere
// on the canvas, the nodes at work kept clear of them wherever they are. And (from the user's
// report, 16 October) the message box and Send always inside the open chat, whatever the tab.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, more, openFreshConversation, say, settled, shot } from './helpers'

const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })
const viewOf = (page: Page) => page.getByRole('region', { name: 'Workspace' })
/** The Workspace window, opened by itself on the chart an agent showed. */
async function openChart(page: Page) {
  await expect(viewOf(page).getByRole('tab', { name: 'chart39.png' })).toHaveAttribute('aria-selected', 'true', { timeout: 10_000 })
}
const box = async (target: Locator) => (await target.boundingBox())!
type Box = { x: number; y: number; width: number; height: number }
const inside = (inner: Box, outer: Box) =>
  inner.x >= outer.x - 1 && inner.y >= outer.y - 1 && inner.x + inner.width <= outer.x + outer.width + 1 && inner.y + inner.height <= outer.y + outer.height + 1
const apart = (a: Box, b: Box) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y

/** Rejects the change the turn asks about and waits for the turn to end on it. (A bare click resolves before its
 * request leaves the page: the test ended, the page closed, and under load the Reject never reached the backend -
 * the turn waited for the user on, holding hello.py, and every later chat here stood in line for the file.) */
async function reject(chat: Locator) {
  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 15_000 })
  await expect(chat.getByRole('button', { name: 'Stop' })).toBeHidden({ timeout: 15_000 })
}

/** Drags a window by a point of its header (left of its middle, clear of its buttons) by (dx, dy). */
async function drag(page: Page, header: Locator, dx: number, dy: number) {
  const at = await box(header.locator('.move-grip'))
  const [x, y] = [at.x + at.width / 2, at.y + at.height / 2]
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx, y + dy, { steps: 8 })
  await page.mouse.up()
}

test.describe('at the size of the user’s window', () => {
  test.use({ viewport: { width: 1017, height: 672 } })

  test('in every tab, at the least height and the first, the message box and Send are inside the open chat (the user’s report)', async ({ page }) => {
    test.setTimeout(120_000)
    await openFreshConversation(page)
    const chat = chatOf(page)
    // Two turns: the Notes tab has its turn to pick, and a notebook closed.
    await say(page, 'hello, everything at once', 'Hello! Ask me to read or change a file.')
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    // A room that waits for the user: its question waits (the room itself is a window: AC; its card is on Ready for you's panel).
    await more(page)
    await chat.getByRole('button', { name: /Work together/ }).click()
    const form = chat.getByRole('form', { name: 'Work together' })
    await form.getByLabel('Goal').fill('Look at the greeting together')
    await form.getByLabel('Posts by its members').fill('12')
    await form.getByRole('button', { name: 'Open the room' }).click()
    const room = page.getByRole('dialog', { name: 'Room: Look at the greeting together' })
    const waiting = room.getByRole('region', { name: 'Waits for you' })
    await expect(waiting.getByText('Shall the greeting stay hi?')).toBeVisible({ timeout: 20_000 })

    for (const [height, kept] of [['the least', '0.2'], ['the first', null]] as const) {
      await page.evaluate(share => (share ? localStorage.setItem('koloni-chat-height', share) : localStorage.removeItem('koloni-chat-height')), kept)
      await page.reload()
      for (const tab of ['Chat', 'Talk', 'Notes']) {
        await chat.getByRole('tab', { name: new RegExp(`^${tab}`) }).click()
        // (an earlier turn picked: its notebook closed, a line more over the list)
        if (tab === 'Notes') {
          await chat.getByRole('combobox', { name: 'Whose notes', exact: true }).selectOption({ index: 0 })
          await expect(chat.getByText(/its notebook is closed/)).toBeVisible()
        }
        const [around, send, model, message] = await Promise.all([box(chat), box(chat.getByRole('button', { name: /^(Send|Queue)$/ })), box(chat.getByRole('button', { name: /^Model: / })), box(chat.getByLabel('Message'))])
        for (const [what, part] of [['Send', send], ['the model', model], ['the message box', message]] as const)
          expect(inside(part, around), `${what} inside the chat on its ${tab} tab at ${height} height`).toBe(true)
      }
    }
    // (The room is left over: the Coder answered, so that it ends. After the reload it is a tab at the canvas's foot.)
    await page.getByRole('group', { name: 'Rooms' }).getByRole('button', { name: /^Room · Look at the greeting together/ }).click()
    await waiting.getByLabel('Your answer').fill('Yes')
    await waiting.getByRole('button', { name: 'Send answer' }).click()
    await expect(room.getByText('done · 1 of 1')).toBeVisible({ timeout: 20_000 })
  })
})

test.describe('on a large window', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('closed, the chat is a small box to type in: Enter sends and it stays closed; a click on its line opens the chat itself with what was typed', async ({ page }) => {
    await openFreshConversation(page)
    const chat = chatOf(page)
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    const line = chat.getByRole('button', { name: /^Chat/ })
    await chat.getByLabel('Message').fill('hello, everything at once')
    await chat.getByLabel('Message').press('Enter')
    await expect(line).toContainText('Hello! Ask me to read or change a file.', { timeout: 20_000 })
    await expect(line).toHaveAttribute('aria-expanded', 'false')
    await expect(chat.getByLabel('Message')).toHaveValue('')
    // (a small box: its line and one line to type in, in the corner)
    const [stage, small] = [await box(page.locator('.stage')), await box(chat)]
    expect(small.height).toBeLessThanOrEqual(100)
    expect(Math.round(small.x - stage.x)).toBe(14)
    await chat.getByLabel('Message').fill('not sent yet')
    await line.click()
    await expect(chat.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
    await expect(chat.getByLabel('Message')).toHaveValue('not sent yet')
    await expect(chat.getByLabel('Message')).toBeFocused()
    // On a narrow canvas the open chat is narrower: Send is its own, inside it.
    await page.setViewportSize({ width: 700, height: 900 })
    await chat.getByRole('tab', { name: 'Chat' }).click()
    const hits = async (target: Locator, inside: string) => {
      const at = await box(target)
      return page.evaluate(([x, y, s]) => !!document.elementFromPoint(x as number, y as number)?.closest(s as string), [at.x + at.width / 2, at.y + at.height / 2, inside])
    }
    expect(await hits(chat.getByRole('button', { name: 'Send' }), '.composer-actions')).toBe(true)
  })

  test('the open chat is dragged anywhere on the canvas and never off it; it is there after a reload; a double click puts it back in its corner', async ({ page }) => {
    await openFreshConversation(page)
    const chat = chatOf(page)
    const header = chat.locator('.chat-top')
    const stage = await box(page.locator('.stage'))
    const corner = await box(chat)
    await drag(page, header, 400, -200)
    const moved = await box(chat)
    expect(Math.round(moved.x - corner.x)).toBe(400)
    expect(Math.round(moved.y - corner.y)).toBe(-200)
    // Far past the right and top edges: it stops at them.
    await drag(page, header, 2000, -2000)
    const stopped = await box(chat)
    expect(Math.round(stopped.x + stopped.width)).toBe(Math.round(stage.x + stage.width))
    expect(Math.round(stopped.y)).toBe(Math.round(stage.y))
    await page.reload()
    await expect(chat.getByLabel('Message')).toBeVisible()
    expect(await box(chat)).toEqual(stopped)
    // Its height still changes from its top edge, where it was moved to: up to half the canvas.
    await expect(chat.getByRole('separator', { name: 'Chat height' })).toHaveAttribute('aria-valuenow', '45')
    await chat.getByRole('separator', { name: 'Chat height' }).focus()
    await page.keyboard.press('ArrowDown')
    await expect.poll(async () => Math.round((await box(chat)).height / stage.height * 100)).toBe(40)
    expect(inside(await box(chat), stage)).toBe(true)
    // The keyboard: 16 px an arrow, from its handle.
    const before = await box(chat)
    await chat.getByRole('button', { name: 'Move chat' }).focus()
    await page.keyboard.press('ArrowLeft')
    await page.keyboard.press('ArrowLeft')
    expect(Math.round(before.x - (await box(chat)).x)).toBe(32)
    await header.dblclick({ position: { x: 4, y: 12 } })
    const back = await box(chat)
    expect(Math.round(back.x - stage.x)).toBe(14)
    expect(Math.round(stage.y + stage.height - back.y - back.height)).toBe(14)
    expect(back.x).toBe(corner.x)
  })

  test('the chat and the Workspace window dragged over the canvas: the nodes at work stay on it, clear of both where they are; the one used last is in front', async ({ page }) => {
    test.setTimeout(90_000)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await page.getByLabel('Message').fill('show the chart')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
    await openChart(page)
    const view = viewOf(page)
    await expect(view.getByRole('tab', { name: 'chart39.png' })).toBeVisible()
    // A command that runs half a minute, without asking: the lead and its command are at work.
    await page.getByLabel('Permission level').selectOption('full_auto')
    await page.getByLabel('Message').fill('run slow.py')
    await page.getByRole('button', { name: 'Send' }).click()
    try {
      const running = page.locator('.react-flow__node').filter({ has: page.locator('.node-running') })
      await expect(page.locator('.react-flow__node-agent .node-running', { hasText: 'slow.py' })).toHaveCount(1, { timeout: 15_000 })
      // The view window up to the top right of the canvas - over the nodes at work - and the chat up to its top left.
      await drag(page, view.locator('.view-top'), 170, -440)
      await drag(page, chat.locator('.chat-top'), 0, -440)
      const clear = async () => {
        const [stage, over, beside] = [await box(page.locator('.canvas-flow')), await box(view), await box(chat)]
        const nodes = await Promise.all((await running.all()).map(node => node.boundingBox()))
        return nodes.length > 0 && nodes.every(node => node !== null && inside(node, stage) && apart(node, over) && apart(node, beside))
      }
      await expect.poll(clear).toBe(true)
      // Whichever was pressed last lies over the other.
      await view.getByRole('tab', { name: 'chart39.png' }).click()
      await expect(view).toHaveAttribute('data-front', '')
      await chat.getByRole('tab', { name: 'Chat' }).click()
      await expect(chat).toHaveAttribute('data-front', '')
      await expect(view).not.toHaveAttribute('data-front', '')
      // Expanded over the canvas, the view covers no part the turn is kept clear of: it is over all of it.
      await view.getByRole('button', { name: 'Expand workspace' }).click()
      await expect(view.getByRole('button', { name: 'Move workspace' })).toHaveCount(0)
      await view.getByRole('button', { name: 'Shrink workspace' }).click()
      await expect.poll(clear).toBe(true)
      // In opposite corners - the chat to the bottom right, the view to the top left - the nodes at work are between them.
      await drag(page, chat.locator('.chat-top'), 2000, 2000)
      await drag(page, view.locator('.view-top'), -2000, 0)
      await expect.poll(clear).toBe(true)
      // Moved as far into the bottom right as it goes, the chat leaves the canvas's zoom buttons (slice 66) to be pressed.
      const zoomIn = page.getByRole('button', { name: 'Zoom In' })
      const at = await box(zoomIn)
      expect(await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('.react-flow__controls'), [at.x + at.width / 2, at.y + at.height / 2])).toBe(true)
    } finally {
      // (Stopped, so that nothing runs on into the next test.)
      if (await chat.getByRole('button', { name: 'Stop' }).isVisible()) await chat.getByRole('button', { name: 'Stop' }).click()
      await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
    }
  })

  test('the Workspace window: a tab each, × closes a tab, its button closes and opens it; dragged, it stays where it was put', async ({ page }) => {
    test.setTimeout(60_000)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await page.getByLabel('Message').fill('show the chart')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
    await openChart(page)
    const view = viewOf(page)
    const files = page.getByRole('button', { name: /^Workspace/ })
    await expect(view.getByRole('tab', { name: 'chart39.png' })).toHaveAttribute('aria-selected', 'true')
    await expect(files).toHaveAttribute('aria-expanded', 'true')
    const before = await box(view)
    await drag(page, view.locator('.view-top'), -200, -150)
    const after = await box(view)
    expect(Math.round(before.x - after.x)).toBe(200)
    // (its ×: for the mouse; Delete closes it from the keyboard) - the file stays in the tree
    await view.getByRole('tab', { name: 'chart39.png' }).locator('.view-tab-close').click()
    await expect(view.getByRole('tablist', { name: 'Open files' }).getByRole('tab')).toHaveCount(0)
    await expect(view.getByText('Pick a file in the tree.')).toBeVisible()
    await files.click()
    await expect(view).toBeHidden()
    await expect(files).toBeFocused()
    await files.click()
    await expect(view.getByRole('treeitem', { name: /^chart39\.png/ })).toBeVisible()
    expect(await box(view)).toEqual(after)
    await view.locator('.view-top').dblclick({ position: { x: 4, y: 4 } })
    expect(await box(view)).toEqual(before)
  })
})

// Taken on request (KOLONI_SHOTS=1): runtime/shots/38e-*.png.
for (const theme of ['light', 'dark'] as const)
  test(`shots: the chat of slice 38e, ${theme}`, async ({ page }) => {
    test.skip(!process.env.KOLONI_SHOTS, 'screenshots are taken with KOLONI_SHOTS=1')
    test.setTimeout(90_000)
    await page.setViewportSize({ width: 1440, height: 900 })
    const snap = (name: string) => shot(page, `38e-${name}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await say(page, 'review the greeting', 'The reviewer found no problems.')
    await page.getByLabel('Message').fill('show the chart')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('There is the chart.')).toBeVisible({ timeout: 20_000 })
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await expect(page.locator('.chat-dock').getByRole('button', { name: /^Workspace/ })).toBeVisible()
    await page.getByLabel('Message').fill('a message typed in the small box')
    await settled(page)
    await snap('closed')
    await chat.getByRole('button', { name: /^Chat/ }).click()
    await settled(page)
    await snap('open')
    await openChart(page)
    await expect(viewOf(page).getByRole('img', { name: 'chart39.png' })).toBeVisible()
    await settled(page)
    await snap('images')
    // The view window to the top left, the chat to the bottom right; Fit View draws the turn between them.
    await drag(page, viewOf(page).locator('.view-top'), -2000, -2000)
    await drag(page, chat.locator('.chat-top'), 2000, 2000)
    await page.getByRole('button', { name: 'Fit View' }).click()
    await settled(page)
    const [stage, nodes] = [await box(page.locator('.canvas-flow')), await page.locator('.react-flow__node').all()]
    for (const node of nodes) {
      const at = await box(node)
      expect(inside(at, stage) && apart(at, await box(chat)) && apart(at, await box(viewOf(page)))).toBe(true)
    }
    await snap('moved')
    await page.setViewportSize({ width: 1017, height: 672 })
    await chat.locator('.chat-top').dblclick({ position: { x: 4, y: 12 } })
    await viewOf(page).getByRole('button', { name: 'Close workspace' }).click()
    await chat.getByRole('tab', { name: 'Notes' }).click()
    await settled(page)
    await snap('notes-small')
  })

// The user's report (batch-14): after Send, Stop and Queue came and part of the row under the message box went on a
// second line. Its controls stand on one line while a turn runs too, in both themes, on a wide window and a narrow one.
for (const theme of ['light', 'dark'] as const)
  for (const width of [1440, 700, 600, 574])
    test(`while a turn runs the row under the message box is one line, ${width}px wide, ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
      await openFreshConversation(page)
      const chat = chatOf(page)
      await page.getByLabel('Message').fill('change the greeting again')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
      await expect(chat.getByRole('button', { name: 'Stop' })).toBeVisible()
      const row = chat.locator('.composer-controls')
      const { around, parts } = await row.evaluate(el => ({
        around: el.getBoundingClientRect().toJSON() as DOMRect,
        parts: [...el.querySelectorAll('select, label, button')]
          .filter(c => (c as HTMLElement).offsetParent && !c.closest('[hidden]'))
          .map(c => ({ name: c.getAttribute('aria-label') ?? c.textContent, top: c.getBoundingClientRect().top, right: c.getBoundingClientRect().right })),
      }))
      expect(parts.map(part => part.name)).toEqual(expect.arrayContaining(['Permission level', 'More', 'Stop', 'Queue']))
      for (const part of parts) {
        // (each in the row's one line, and none past its end)
        expect(part.top - around.top, `${part.name} on the first line`).toBeLessThan(12)
        expect(part.right, `${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
      }
      expect(around.height).toBeLessThanOrEqual(36)
      await reject(chat)
    })

// R56: with "Ask before changes" chosen the row went on two lines in a chat 240px wide. One line down to the narrowest chat (220px).
for (const width of [574, 554])
  test(`the row under the message box is one line in a chat ${width - 334}px wide, "Ask before changes" chosen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openFreshConversation(page)
    const chat = chatOf(page)
    await expect(page.getByLabel('Permission level')).toHaveValue('ask')
    expect(Math.round((await box(chat)).width)).toBe(width - 334)
    const row = chat.locator('.composer-controls')
    const { around, parts } = await row.evaluate(el => ({
      around: el.getBoundingClientRect().toJSON() as DOMRect,
      parts: [...el.children].map(c => ({ name: c.className, top: c.getBoundingClientRect().top, right: c.getBoundingClientRect().right })),
    }))
    for (const part of parts) {
      expect(part.top - around.top, `${part.name} on the first line`).toBeLessThan(12)
      expect(part.right, `${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
    }
    expect(around.height).toBeLessThanOrEqual(36)
  })

// The user's pick (7 Nov, sample C, given way in sample A's order): the model's line, then 📎, the level and Send. The
// model's button is one line, cut with "…" (B-400: in a 220px chat its name broke letter by letter); Full auto is read whole.
for (const width of [814, 654, 554])
  test(`two lines, two jobs, in a chat ${width - 334}px wide: the model's button one line, cut with "…"; Full auto read whole`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openFreshConversation(page)
    const chat = chatOf(page)
    await chat.getByRole('button', { name: /^Model: / }).click()
    await page.getByLabel('Provider').selectOption({ label: 'Local' })
    await page.getByLabel('Model name').fill('fake-strong-with-a-long-name')
    await page.getByLabel(/Orchestrator model: automatic/).check()
    await chat.getByRole('button', { name: 'Use this model' }).click()
    const model = chat.getByRole('button', { name: 'Model: Orchestrator: automatic · Local · fake-strong-with-a-long-name', exact: true })
    await expect(model).toHaveAttribute('title', /^Orchestrator: automatic · Local · fake-strong-with-a-long-name: /)
    expect(Math.round((await box(model)).height)).toBe(30)
    const label = model.locator('.model-picker-label')
    expect(await label.evaluate(el => [getComputedStyle(el).whiteSpace, getComputedStyle(el).textOverflow])).toEqual(['nowrap', 'ellipsis'])
    expect(Math.round((await box(label)).height)).toBeLessThan(20)
    await expect(chat.locator('.composer-controls').getByRole('button', { name: 'Attach' })).toBeVisible()
    await chat.getByLabel('Permission level').selectOption('full_auto')
    const level = chat.getByLabel('Permission level')
    await expect(level).toHaveCSS('flex-shrink', '0')
    // (as wide as it is with room for all of its name)
    expect(
      await level.evaluate(el => {
        const now = el.getBoundingClientRect().width
        el.style.width = 'max-content'
        const whole = el.getBoundingClientRect().width
        el.style.width = ''
        return now >= whole - 1
      }),
    ).toBe(true)
    for (const row of ['.composer-line', '.composer-controls']) {
      const { around, parts } = await chat.locator(row).evaluate(el => ({
        around: el.getBoundingClientRect().toJSON() as DOMRect,
        parts: [...el.children].map(c => ({ name: c.className, right: c.getBoundingClientRect().right })),
      }))
      for (const part of parts) expect(part.right, `${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
    }
    if (process.env.KOLONI_SHOTS) await shot(chat.locator('.composer'), `38e-composer-${width - 334}`)
  })

// Narrower (sample A): Auto-read and Dictate are under More, a dot on it and its description say so; Plan first is its
// icon, its switch still there for the keys.
for (const width of [654, 554])
  test(`in a chat ${width - 334}px wide the voice is under More, and Plan first's switch is reached from the keyboard`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openFreshConversation(page)
    const chat = chatOf(page)
    const moreButton = chat.getByRole('button', { name: 'More', exact: true })
    await expect(moreButton).toHaveAccessibleDescription('Auto-read and Dictate are in here')
    expect(await moreButton.evaluate(el => getComputedStyle(el, '::after').backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
    const panel = chat.locator('.composer-more-panel')
    await more(page)
    await expect(panel.getByRole('button', { name: 'Auto-read', exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Dictate', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    // (from the level, Tab: the switch, clipped out of sight, takes the focus, and Space turns it on)
    const plan = chat.getByRole('switch', { name: 'Plan first' })
    expect(Math.round((await box(plan)).width)).toBeLessThanOrEqual(1)
    await chat.getByLabel('Permission level').focus()
    await page.keyboard.press('Tab')
    await expect(plan).toBeFocused()
    await page.keyboard.press('Space')
    await expect(plan).toBeChecked()
    await page.keyboard.press('Space')
    await expect(plan).not.toBeChecked()
  })

// Full auto while a turn runs: Stop and Queue are there, and nothing of the row is past its end (in the narrowest chat they
// go on a second line).
for (const width of [814, 574, 554])
  test(`Full auto while a turn runs in a chat ${width - 334}px wide: Stop and Queue, and nothing past the row's end`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openFreshConversation(page)
    const chat = chatOf(page)
    await chat.getByLabel('Permission level').selectOption('full_auto')
    await page.getByLabel('Message').fill('run slow.py')
    await page.getByRole('button', { name: 'Send' }).click()
    try {
      await expect(chat.getByRole('button', { name: 'Stop' })).toBeVisible()
      await expect(chat.getByRole('button', { name: 'Queue' })).toBeVisible()
      const { around, parts } = await chat.locator('.composer-controls').evaluate(el => ({
        around: el.getBoundingClientRect().toJSON() as DOMRect,
        parts: [...el.querySelectorAll('select, label, button')]
          .filter(c => (c as HTMLElement).offsetParent && !c.closest('[hidden]'))
          .map(c => ({ name: c.getAttribute('aria-label') ?? c.textContent, right: c.getBoundingClientRect().right })),
      }))
      for (const part of parts) expect(part.right, `${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
      if (process.env.KOLONI_SHOTS) await shot(chat.locator('.composer'), `38e-composer-full-auto-running-${width - 334}`)
    } finally {
      // (Stopped, so that nothing runs on into the next test.)
      if (await chat.getByRole('button', { name: 'Stop' }).isVisible()) await chat.getByRole('button', { name: 'Stop' }).click()
    }
  })

// R56: a Lead's long option button opened a scrollbar across the chat. Its words wrap in the chat.
test('a long option of a question wraps inside the chat: nothing in it scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  const chat = chatOf(page)
  await page.getByLabel('Message').fill('ask a long choice, r56')
  await page.getByRole('button', { name: 'Send' }).click()
  const long = chat.getByRole('button', { name: /^Go on with the whole plan as written/ })
  await expect(long).toBeVisible()
  expect((await box(long)).x + (await box(long)).width).toBeLessThanOrEqual((await box(chat)).x + (await box(chat)).width)
  const sideways = await chat.evaluate(root =>
    [root, ...root.querySelectorAll('*')]
      .filter(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1)
      .map(el => el.className),
  )
  expect(sideways).toEqual([])
  await chat.getByRole('button', { name: 'Stop here' }).click()
  // (Its answer heard, as the Reject above: a turn left asking would be counted by the next spec's badge.)
  await expect(chat.getByText('Going with Stop here.')).toBeVisible({ timeout: 15_000 })
})

// Batch-18 review: in a chat between 220px and 240px wide, while a turn ran, Queue went past the row's end. It goes on a second
// line there, inside the row, as in the narrowest chat.
// And with something waiting in another chat: its line is one line, and the messages keep their room - Reject is
// there to click (it once had none: the line took two lines, and the message list 0px).
for (const width of [564, 554])
  test(`while a turn runs in a chat ${width - 334}px wide nothing of the row is past its end`, async ({ page }) => {
    test.setTimeout(60_000) // (two turns)
    // A question waits in another chat; answered at the end, it is left to no spec after.
    const other = await openFreshConversation(page)
    await page.getByLabel('Message').fill('ask a long choice, r56')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chatOf(page).getByRole('button', { name: 'Stop here' })).toBeVisible({ timeout: 15_000 })
    try {
      await page.setViewportSize({ width, height: 900 })
      await openFreshConversation(page)
      const chat = chatOf(page)
      await page.getByLabel('Message').fill('change the greeting again')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByRole('button', { name: 'Stop' })).toBeVisible()
      const { around, parts } = await chat.locator('.composer-controls').evaluate(el => ({
        around: el.getBoundingClientRect().toJSON() as DOMRect,
        parts: [...el.children].map(c => ({ name: c.className, right: c.getBoundingClientRect().right })),
      }))
      for (const part of parts) expect(part.right, `${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
      const elsewhere = chat.getByRole('button', { name: /^Open Ready for you: \d+ more waits? elsewhere$/ })
      await expect(elsewhere).toBeVisible()
      await expect(chat.getByRole('button', { name: 'Reject' })).toBeVisible({ timeout: 15_000 })
      expect((await box(chat.locator('.ready-line'))).height).toBeLessThan(40)
      expect((await box(chat.locator('.chat-pane'))).height).toBeGreaterThanOrEqual(100)
      await reject(chat)
    } finally {
      for (const asked of (await (await page.request.get(`/api/conversations/${other}`)).json()).questions ?? [])
        if (asked.status === 'pending') await page.request.post(`/api/questions/${asked.id}/answer`, { data: { answer: 'Stop here' }, headers: OWN })
    }
  })
