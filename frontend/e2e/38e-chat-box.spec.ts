// Slice 38e in the browser: the chat as the reference has it - a small box to type in while
// closed, Workspace beside it - and the Workspace window dragged anywhere on the canvas beside
// the open chat's column (0.1.4), the nodes at work kept clear of both wherever it is. And (from
// the user's report, 16 October) the message box and Send always inside the open chat, whatever the tab.
import { expect, test, type Locator, type Page } from './fixtures'
import { level, more, openFreshConversation, OWN, say, settled, shot } from './helpers'

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

/** Drags a window by its grip, at the left of its header, by (dx, dy). */
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

  test('in every tab, at the least width and the first, the message box and Send are inside the open chat (the user’s report)', async ({ page }) => {
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

    for (const [width, kept] of [['the least', '340'], ['the first', null]] as const) {
      await page.evaluate(px => (px ? localStorage.setItem('koloni-chat-width', px) : localStorage.removeItem('koloni-chat-width')), kept)
      await page.reload()
      for (const tab of ['Chat', 'Talk', 'Notes']) {
        await chat.getByRole('tab', { name: new RegExp(`^${tab}`) }).click()
        // (an earlier turn picked: its notebook closed, a line more over the list)
        if (tab === 'Notes') {
          await chat.getByRole('combobox', { name: 'Whose notes', exact: true }).selectOption({ index: 0 })
          await expect(chat.getByText(/its notebook is closed/)).toBeVisible()
        }
        // (0.1.5: the model is on the line over the box while the chat is ready; the room keeps this turn at work.)
        const [around, send, line, message] = await Promise.all([box(chat), box(chat.getByRole('button', { name: /^(Send|Queue)$/ })), box(chat.locator('.composer-status')), box(chat.getByLabel('Message'))])
        for (const [what, part] of [['Send', send], ['the line over the box', line], ['the message box', message]] as const)
          expect(inside(part, around), `${what} inside the chat on its ${tab} tab at ${width} width`).toBe(true)
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

  test('the Workspace window dragged over the canvas beside the chat’s column: the nodes at work stay on it, clear of both where they are; the one used last is in front', async ({ page }) => {
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
    await level(page, 'full_auto')
    await page.getByLabel('Message').fill('run slow.py')
    await page.getByRole('button', { name: 'Send' }).click()
    try {
      const running = page.locator('.react-flow__node').filter({ has: page.locator('.node-running') })
      await expect(page.locator('.react-flow__node-agent .node-running', { hasText: 'slow.py' })).toHaveCount(1, { timeout: 15_000 })
      // The view window up to the top right of the canvas - over the nodes at work.
      await drag(page, view.locator('.view-top'), 170, -440)
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
      // The view in the bottom right corner, the chat's column at the left: the nodes at work are between them.
      await drag(page, view.locator('.view-top'), 2000, 2000)
      await expect.poll(clear).toBe(true)
      // Moved as far into the bottom right as it goes, the view leaves the canvas's zoom buttons (slice 66) to be pressed.
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
    // The view window to the bottom right, the chat's column at the left; Fit View draws the turn between them.
    await drag(page, viewOf(page).locator('.view-top'), 2000, 2000)
    await page.getByRole('button', { name: 'Fit View' }).click()
    await settled(page)
    const [stage, nodes] = [await box(page.locator('.canvas-flow')), await page.locator('.react-flow__node').all()]
    for (const node of nodes) {
      const at = await box(node)
      expect(inside(at, stage) && apart(at, await box(chat)) && apart(at, await box(viewOf(page)))).toBe(true)
    }
    await snap('moved')
    await page.setViewportSize({ width: 1017, height: 672 })
    await viewOf(page).getByRole('button', { name: 'Close workspace' }).click()
    await chat.getByRole('tab', { name: 'Notes' }).click()
    await settled(page)
    await snap('notes-small')
  })

// 0.1.5, "Kovan konsolu": the box's line over the message, its own row under it, and the quiet row under the box - each
// one line, inside the chat, whatever its width (the user's reports, batch-14, R56, batch-18: rows went on two lines).
async function oneLine(chat: Locator) {
  for (const row of ['.composer-status', '.composer-bar', '.composer-below']) {
    const { around, parts, end } = await chat.locator(row).evaluate(el => ({
      around: el.getBoundingClientRect().toJSON() as DOMRect,
      end: el.closest('.chat')!.getBoundingClientRect().right,
      parts: [...el.children]
        .filter(c => (c as HTMLElement).offsetParent !== null && getComputedStyle(c).position !== 'absolute')
        .map(c => ({ name: c.getAttribute('aria-label') ?? c.className, top: c.getBoundingClientRect().top, bottom: c.getBoundingClientRect().bottom, right: c.getBoundingClientRect().right })),
    }))
    for (const part of parts) {
      expect(part.top - around.top, `${row} ${part.name} on its one line`).toBeLessThan(12)
      expect(part.right, `${row} ${part.name} inside the row`).toBeLessThanOrEqual(around.right + 1)
    }
    expect(around.right, `${row} inside the chat`).toBeLessThanOrEqual(end + 1)
    expect(around.height, `${row} one line`).toBeLessThanOrEqual(40)
  }
}

for (const theme of ['light', 'dark'] as const)
  for (const width of [1440, 700, 600, 574])
    test(`while a turn runs each row of the message box is one line, ${width}px wide, ${theme} theme`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
      await openFreshConversation(page)
      const chat = chatOf(page)
      await page.getByLabel('Message').fill('change the greeting again')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
      // (Stop is on the line over the message box; Queue in Send's place.)
      await expect(chat.locator('.composer-status').getByRole('button', { name: 'Stop' })).toBeVisible()
      await expect(chat.locator('.composer-bar').getByRole('button', { name: 'Queue' })).toBeVisible()
      await oneLine(chat)
      await reject(chat)
    })

async function chatWide(page: Page, width: number) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(px => localStorage.setItem('koloni-chat-width', String(px)), width)
  await openFreshConversation(page)
  expect(Math.round((await box(chatOf(page))).width)).toBe(width)
}

for (const width of [574])
  test('each row of the message box is one line in the narrowest chat, "Ask before changes" chosen', async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openFreshConversation(page)
    const chat = chatOf(page)
    await expect(chat.getByRole('button', { name: 'Permission level: Ask before changes' })).toBeVisible()
    expect(Math.round((await box(chat)).width)).toBe(340)
    await oneLine(chat)
  })

// The model on the line over the box, one line, cut with "…" (B-400: in a 220px chat its name broke letter by letter) - and
// at its narrowest its arrow alone, its name in its tooltip; the level's name read whole, Full auto too.
for (const width of [480, 340])
  test(`in a chat ${width}px wide the model is one line over the box, the level's name read whole`, async ({ page }) => {
    await chatWide(page, width)
    const chat = chatOf(page)
    await chat.getByRole('button', { name: /^Model: / }).click()
    await page.getByLabel('Provider').selectOption({ label: 'Local' })
    await page.getByLabel('Model name').fill('fake-strong-with-a-long-name')
    await page.getByLabel(/Orchestrator model: automatic/).check()
    await chat.getByRole('button', { name: 'Use this model' }).click()
    const model = chat.getByRole('button', { name: 'Model: Orchestrator: automatic · Local · fake-strong-with-a-long-name', exact: true })
    await expect(model).toHaveAttribute('title', /^Orchestrator: automatic · Local · fake-strong-with-a-long-name: /)
    expect(await model.evaluate(el => el.closest('.composer-status') !== null)).toBe(true)
    const label = model.locator('.model-picker-label')
    if (width > 450) {
      expect(await label.evaluate(el => [getComputedStyle(el).whiteSpace, getComputedStyle(el).textOverflow])).toEqual(['nowrap', 'ellipsis'])
      expect(Math.round((await box(label)).height)).toBeLessThan(20)
    } else await expect(label).toBeHidden()
    await expect(chat.locator('.composer-bar').getByRole('button', { name: 'Attach' })).toBeVisible()
    await level(page, 'full_auto')
    const name = chat.locator('.composer-level-name')
    await expect(name).toHaveText('Full auto')
    expect(await name.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await oneLine(chat)
    if (process.env.KOLONI_SHOTS) await shot(chat.locator('.composer'), `38e-composer-${width}`)
  })

/** A question left waiting in another chat, so that this one has something waiting elsewhere; its chat's id. */
async function askElsewhere(page: Page) {
  const other = await openFreshConversation(page)
  await page.getByLabel('Message').fill('ask a long choice, r56')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chatOf(page).getByRole('radio', { name: 'Stop here' })).toBeAttached({ timeout: 15_000 })
  return other
}

/** Answers what `askElsewhere` left waiting: no spec after is left with it. */
async function answerElsewhere(page: Page, other: string) {
  for (const asked of (await (await page.request.get(`/api/conversations/${other}`)).json()).questions ?? [])
    if (asked.status === 'pending') await page.request.post(`/api/questions/${asked.id}/answer`, { data: { answer: 'Stop here' }, headers: OWN })
}

// Full auto while a turn runs, a question waiting in another chat: Stop over the box, Queue in its row, and each row one
// line inside the chat - what waits elsewhere in fewer words where the row has no room for more; Settings keeps its word.
for (const width of [520, 480, 420, 340])
  test(`Full auto while a turn runs in a chat ${width}px wide, a question waiting elsewhere: Stop and Queue, and each row one line`, async ({ page }) => {
    test.setTimeout(60_000) // (two turns)
    const other = await askElsewhere(page)
    try {
      await chatWide(page, width)
      const chat = chatOf(page)
      await level(page, 'full_auto')
      await page.getByLabel('Message').fill('run slow.py')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByRole('button', { name: 'Stop' })).toBeVisible()
      await expect(chat.getByRole('button', { name: 'Queue' })).toBeVisible()
      await expect(chat.getByRole('button', { name: /^Open Ready for you: \d+ more waits? elsewhere$/ })).toBeVisible()
      await expect(chat.getByRole('button', { name: 'This chat’s settings' })).toHaveText(/Settings/)
      expect((await box(chat.locator('.chat-sheet-button .composer-words'))).width, 'Settings in words').toBeGreaterThan(30)
      await oneLine(chat)
      if (process.env.KOLONI_SHOTS) await shot(chat.locator('.composer'), `38e-composer-full-auto-running-${width}`)
    } finally {
      // (Stopped, so that nothing runs on into the next test.)
      const stop = chatOf(page).getByRole('button', { name: 'Stop' })
      if (await stop.isVisible()) await stop.click()
      await answerElsewhere(page, other)
    }
  })

// R56: a Lead's long option button opened a scrollbar across the chat. Its words wrap in the chat.
test('a long option of a question wraps inside the chat: nothing in it scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  const chat = chatOf(page)
  await page.getByLabel('Message').fill('ask a long choice, r56')
  await page.getByRole('button', { name: 'Send' }).click()
  // (0.1.5: an option is a row of the card over the message box, its radio in it.)
  const card = chat.getByRole('form', { name: 'Orchestrator asks' })
  const long = card.locator('.ask-option', { has: page.getByRole('radio', { name: /^Go on with the whole plan as written/ }) })
  await expect(long).toBeVisible()
  expect((await box(long)).x + (await box(long)).width).toBeLessThanOrEqual((await box(chat)).x + (await box(chat)).width)
  const sideways = await chat.evaluate(root =>
    [root, ...root.querySelectorAll('*')]
      .filter(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1)
      .map(el => el.className),
  )
  expect(sideways).toEqual([])
  await card.getByRole('radio', { name: 'Stop here' }).check()
  await card.getByRole('button', { name: 'Submit' }).click()
  // (Its answer heard, as the Reject above: a turn left asking would be counted by the next spec's badge.)
  await expect(chat.getByText('Going with Stop here.')).toBeVisible({ timeout: 15_000 })
})

// Batch-18 review: in a chat between 220px and 240px wide, while a turn ran, Queue went past the row's end. It goes on a second
// line there, inside the row, as in the narrowest chat (340px since 0.1.4, on this window too).
// And with something waiting in another chat: its line is one line, and the messages keep their room - Reject is
// there to click (it once had none: the line took two lines, and the message list 0px).
for (const width of [574])
  test('while a turn runs in the narrowest chat nothing of the row is past its end', async ({ page }) => {
    test.setTimeout(60_000) // (two turns)
    // A question waits in another chat; answered at the end, it is left to no spec after.
    const other = await askElsewhere(page)
    try {
      await page.setViewportSize({ width, height: 900 })
      await openFreshConversation(page)
      const chat = chatOf(page)
      await page.getByLabel('Message').fill('change the greeting again')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByRole('button', { name: 'Stop' })).toBeVisible()
      await oneLine(chat)
      // (0.1.5: what waits elsewhere is quiet words under the box, in its row's one line.)
      const elsewhere = chat.getByRole('button', { name: /^Open Ready for you: \d+ more waits? elsewhere$/ })
      await expect(elsewhere).toBeVisible()
      await expect(chat.getByRole('button', { name: 'Reject' })).toBeVisible({ timeout: 15_000 })
      expect((await box(elsewhere)).height).toBeLessThan(30)
      expect((await box(chat.locator('.chat-pane'))).height).toBeGreaterThanOrEqual(100)
      await reject(chat)
    } finally {
      await answerElsewhere(page, other)
    }
  })
