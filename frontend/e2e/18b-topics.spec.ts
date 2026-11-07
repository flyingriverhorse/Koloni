import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, openTurns, shot, agentFold, openAgentFold } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const FIRST = 'ask a coder to add a farewell'
const SECOND = 'tell the coder to say goodbye'

/** No trigger and none of the files this spec's turns write is left behind: the specs share the backend. */
async function tidy(request: APIRequestContext) {
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    const triggers: { id: string }[] = await (await request.get(`/api/projects/${project.id}/triggers`)).json()
    for (const trigger of triggers) await request.delete(`/api/triggers/${trigger.id}`, { headers: OWN })
  }
  for (const file of ['farewell.py', 'made.txt']) rmSync(path.join(PROJECT_DIR, file), { force: true })
}

test.beforeEach(async ({ request }) => {
  await tidy(request)
})

test.afterEach(async ({ request }) => {
  await tidy(request)
})

async function say(page: Page, text: string, answer: string, times = 1) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText(answer)).toHaveCount(times, { timeout: 20_000 })
}

/** Whether any two nodes that are not one inside the other lie on each other. */
async function overlapping(page: Page) {
  return page.locator('.react-flow__node').evaluateAll(all => {
    const rects = all.map(n => ({ id: (n as HTMLElement).dataset.id ?? '', box: n.getBoundingClientRect() }))
    const inside = (a: DOMRect, b: DOMRect) => a.left >= b.left - 1 && a.top >= b.top - 1 && a.right <= b.right + 1 && a.bottom <= b.bottom + 1
    const found: string[] = []
    for (const a of rects) {
      for (const b of rects) {
        if (a.id >= b.id || inside(a.box, b.box) || inside(b.box, a.box)) continue
        const apart = a.box.right <= b.box.left + 1 || b.box.right <= a.box.left + 1 || a.box.bottom <= b.box.top + 1 || b.box.bottom <= a.box.top + 1
        if (!apart) found.push(`${a.id} on ${b.id}`)
      }
    }
    return found
  })
}

/** Whether one thing lies wholly inside another, as they are drawn. */
async function holds(outer: Locator, inner: Locator) {
  const [box, piece] = [await outer.boundingBox(), await inner.boundingBox()]
  if (!box || !piece) return false
  return piece.x >= box.x - 1 && piece.y >= box.y - 1 && piece.x + piece.width <= box.x + box.width + 1 && piece.y + piece.height <= box.y + box.height + 1
}

/** Whether two things, as they are drawn, do not lie on each other. */
async function apart(one: Locator, other: Locator) {
  const [a, b] = [await one.boundingBox(), await other.boundingBox()]
  if (!a || !b) return false
  return a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y
}

/** How big the canvas draws the turn: 1 is life-size. */
const zoom = (page: Page) => page.locator('.react-flow__viewport').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)

/** The canvas moves its view over a fifth of a second: a picture taken for a person is taken after that. */
const settled = (page: Page) => page.waitForTimeout(400)

/** How big a node is in the canvas's own measure, whatever the zoom. */
const size = (node: Locator) => node.evaluate(element => [(element as HTMLElement).offsetWidth, (element as HTMLElement).offsetHeight])

/** Whether a one-line text is drawn whole: none of it is cut off by the box it is in. */
const readInFull = (text: Locator) =>
  text.evaluate(element => {
    // (Measured as drawn: a text a fraction of a pixel too wide is already cut to "…", and the box's whole-pixel widths do not show it.)
    const range = document.createRange()
    range.selectNodeContents(element)
    return range.getBoundingClientRect().width <= element.getBoundingClientRect().width + 0.02
  })

/** The first two turns: a Coder is opened and writes a file; then, by default in the same topic, the lead goes on with it. */
async function twoTurns(page: Page) {
  await autoEdit(page)
  await say(page, FIRST, 'The coder added a farewell.')
  await say(page, SECOND, 'The coder changed it: it says goodbye.')
}

/** Files are written without asking, so neither the Coder nor its change waits for a decision. */
async function autoEdit(page: Page) {
  // (Once the new conversation is open: its own settings are on the page then.)
  await expect(page.getByRole('button', { name: 'This chat’s settings' })).toBeAttached() // (⚙ Chat: there with a chat)
  await page.getByLabel('Permission level').selectOption('auto_edit')
  await expect(page.getByLabel('Permission level')).toHaveValue('auto_edit')
}

test('a message goes on with the topic: Recent names it, the canvas draws this turn alone, and the Coder carries on with what it did', async ({ page, request }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const list = page.getByRole('complementary', { name: 'Recent' })
  const turns = list.locator('.turn-row')
  // (No "Continuing" line: "New topic" beside the model says in its tooltip which topic the message goes on with.)
  const line = chat.getByRole('button', { name: 'New topic' })
  const goesOn = (topic: string) => expect(line).toHaveAttribute('title', `Your next message goes on with ${topic}: press to start a new topic`)
  const agents = page.locator('.react-flow__node-agent')
  const requests = page.locator('.react-flow__node-request .node-text')
  const coder = agents.filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // With no topic yet nothing is said about topics.
  await expect(page.getByLabel('Message')).toBeVisible()
  await expect(line).toHaveCount(0)

  // --- turn 1 opens a Coder; turn 2, sent with nothing chosen, goes on with the same topic ----
  await autoEdit(page)
  await say(page, FIRST, 'The coder added a farewell.')
  await openTurns(page)
  await expect(turns).toHaveCount(1)
  await expect(turns).toContainText(FIRST)
  // (its work: the Coder, and the file it wrote)
  await expect(turns).toContainText('1 agent · 1 file')
  await expect(list.getByText(`Topic: ${FIRST}`)).toBeVisible()
  await goesOn(`${FIRST}`)
  await expect(agents).toHaveCount(2)
  await expect(coder).not.toContainText('continues from')

  await say(page, SECOND, 'The coder changed it: it says goodbye.')
  // Recent: the two messages, the newest drawn - of the one topic.
  await openTurns(page)
  await expect(turns).toHaveCount(2)
  await expect(turns.first()).toContainText(SECOND)
  await expect(turns.first()).toContainText('done')
  await expect(turns.first()).toHaveAttribute('aria-current', 'true')
  await expect(list.getByText(`Topic: ${FIRST}`)).toBeVisible()
  // The chat has no divider: the topic did not change.
  await expect(chat.locator('.msg-list').getByRole('separator')).toHaveCount(0)

  // The canvas: this turn in full, nothing of turn 1.
  await expect(requests).toHaveText([SECOND])
  await expect(agents).toHaveCount(2)
  // The Coder is one small node (the user's, 5 Nov): its name read in full - where it runs gives way first -, its file
  // counted; where it goes on from is said in the side panel.
  expect(await readInFull(coder.locator('.node-title'))).toBe(true)
  await expect(coder).toContainText('1 file')
  expect((await size(coder.locator('.node')))[1]).toBe(80)
  await expect.poll(() => overlapping(page)).toEqual([])
  await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
  await settled(page)
  await shot(page, '18b-canvas-topic-light')

  // Its window: what it did in turn 1 is above this turn's work, folded; opened, it has the task, the work and the report.
  // (Selected first: the inspector opens and the stage narrows, and a double click must land twice on the node.)
  const drawnAt = await zoom(page)
  await coder.locator('.node-title').click()
  await expect(inspector).toContainText(/continues from the .+ message/)
  // The inspector took a third of the stage: the turn is drawn as big as it was - not squeezed
  // into what is left - and the view only moved, to keep the Coder in it.
  await settled(page)
  expect(await zoom(page)).toBeCloseTo(drawnAt, 3)
  await expect.poll(() => holds(page.locator('.canvas-flow'), coder)).toBe(true)
  await coder.locator('.node-title').dblclick()
  const window = page.getByRole('region', { name: 'Agent window' })
  await expect(window).toContainText(/continues from the .+ message/)
  // Its window lies over the stage: the Coder is moved out from under it, still as big.
  await expect.poll(() => apart(coder, window)).toBe(true)
  await expect.poll(() => holds(page.locator('.canvas-flow'), coder)).toBe(true)
  await settled(page)
  expect(await zoom(page)).toBeCloseTo(drawnAt, 3)
  expect(await apart(coder, window)).toBe(true)
  // It knew what it had done: only the work of turn 1 says so.
  await expect(window).toContainText('It says goodbye now; before, I had made it say bye.')
  const fold = agentFold(window, 'Earlier work')
  await expect(fold.locator('summary')).toContainText(/^Earlier work the .+ message · 1 file$/)
  await expect(fold).not.toHaveAttribute('open')
  await expect(window.getByText('Added farewell.py: it says bye.')).toBeHidden()
  await openAgentFold(window, 'Earlier work')
  const then = window.getByRole('group', { name: /^The .+ message$/ })
  await expect(then).toContainText('Add farewell.py that says bye')
  await expect(then).toContainText('farewell.py')
  await expect(then.getByText('Added farewell.py: it says bye.')).toHaveCount(1)
  await shot(page, '18b-agent-window-earlier-work')
  await window.getByRole('button', { name: 'Close agent window' }).click()
  await inspector.getByRole('button', { name: 'Close inspector' }).click()

  // Picked in Recent, turn 1 is drawn in its place.
  await openTurns(page)
  await turns.filter({ hasText: FIRST }).click()
  await expect(requests).toHaveText([FIRST])
  await openTurns(page)
  await expect(turns.last()).toHaveAttribute('aria-current', 'true')
  await expect.poll(() => overlapping(page)).toEqual([])
  await expect(inspector).toHaveCount(0)
  await settled(page)
  await shot(page, '18b-canvas-earlier-turn')
  // The Coder of turn 1 says where it went on, and that leads back to turn 2.
  await coder.locator('.node-title').click()
  await inspector.getByRole('button', { name: /^went on in the .+ message$/ }).click()
  await expect(requests).toHaveText([SECOND])
  await expect(inspector).toContainText(/continues from the .+ message/)
  await inspector.getByRole('button', { name: 'Close inspector' }).click()

  // --- "New topic": the next message starts one, and the canvas shows nothing of the first ----
  await goesOn(`${FIRST}`)
  await shot(page.locator('.composer'), '18b-composer-continuing')
  await line.click()
  await expect(line).toHaveAttribute('aria-pressed', 'true')
  await expect(line).toHaveAttribute('title', `Your next message starts a new topic: press again to go on with ${FIRST}`)
  await shot(page.locator('.composer'), '18b-composer-new-topic')
  await say(page, 'hi again', 'Hello! Ask me to read or change a file.')
  await expect(chat.locator('.msg-list').getByRole('separator')).toHaveText('New topic: hi again')
  await openTurns(page)
  await expect(turns).toHaveCount(3)
  await expect(turns.first()).toContainText('hi again')
  // A plain answer: the last message with work stays in front (slice 107) ...
  await expect(requests).toHaveText([SECOND])
  // (the canvas's front is not where the next message goes: that is the topic last written in)
  await goesOn('hi again')
  // ... and a click on it in the chat draws it alone.
  await chat.locator('.msg-bubble', { hasText: 'hi again' }).click()
  await expect(requests).toHaveText(['hi again'])
  await expect(agents).toHaveCount(1)
  // The choice was for that one message: the line is back to continuing, now with the new topic.
  await goesOn('hi again')

  // The topic is renamed in place; the line and the chat's divider follow.
  await openTurns(page)
  await list.getByRole('button', { name: 'Rename hi again' }).click()
  await openTurns(page)
  await list.getByRole('textbox', { name: 'Topic name' }).fill('A greeting')
  await page.keyboard.press('Enter')
  await openTurns(page)
  await expect(list.getByText('Topic: A greeting')).toBeVisible()
  await goesOn('A greeting')
  await expect(chat.locator('.msg-list').getByRole('separator')).toHaveText('New topic: A greeting')

  // --- an earlier topic picked in Recent: the message goes to that one, and the line says so ---
  await openTurns(page)
  await turns.filter({ hasText: SECOND }).click()
  await expect(requests).toHaveText([SECOND])
  await goesOn(`${FIRST}`)
  await say(page, 'hello once more', 'Hello! Ask me to read or change a file.', 2)
  await openTurns(page)
  await expect(turns.first()).toContainText('hello once more')
  await expect(chat.locator('.msg-list').getByRole('separator').last()).toHaveText(`Continuing: ${FIRST}`)
  // (a plain answer: the last message with work is in front)
  await expect(requests).toHaveText([SECOND])
  await expect(list.getByText(`Topic: ${FIRST}`)).toBeVisible()
  await expect.poll(() => overlapping(page)).toEqual([])
  // On record: the four turns are in two topics, the last with the first two.
  const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
  const conversations: { id: string; title: string }[] = await (await request.get(`/api/projects/${project.id}/conversations`)).json()
  const conversation = conversations.find(c => c.title === FIRST)!
  const snap: { runs: { topic_id: string }[]; topics: { id: string; title: string }[] } = await (await request.get(`/api/conversations/${conversation.id}`)).json()
  expect(snap.topics.map(t => t.title)).toEqual([FIRST, 'A greeting'])
  expect(snap.runs.map(r => r.topic_id)).toEqual([snap.topics[0].id, snap.topics[0].id, snap.topics[1].id, snap.topics[0].id])

  // --- a trigger's turns are a topic of their own ------------------------------------------------
  const made = await request.post(`/api/projects/${project.id}/triggers`, {
    headers: OWN,
    data: { name: 'Nightly check', kind: 'webhook', conversation_id: conversation.id, message: 'Do the nightly check.' },
  })
  expect(made.status()).toBe(201)
  const trigger: { id: string } = await made.json()
  expect((await request.post(`/api/triggers/${trigger.id}/run`, { headers: OWN })).ok()).toBe(true)
  const scheduled = turns.filter({ hasText: 'Nightly check' })
  await openTurns(page)
  await expect(scheduled).toContainText('done', { timeout: 20_000 })
  // It took neither the canvas nor the topic the next message goes to.
  await expect(requests).toHaveText([SECOND])
  await goesOn(`${FIRST}`)
  await expect(chat.locator('.msg-list').getByRole('separator').last()).toHaveText('New topic: Nightly check')
  await expect(chat.getByRole('note', { name: 'Started by the trigger Nightly check' })).toBeVisible()
  await openTurns(page)
  await shot(list, '18b-turn-list-topics')
  // Its turn picked: looking at it does not send the next message into the trigger's topic.
  // The line still names the user's own, and offers the trigger's instead.
  await openTurns(page)
  await scheduled.click()
  await expect(requests).toHaveText(['Do the nightly check.'])
  await goesOn(`${FIRST}`)
  const into = chat.getByRole('button', { name: 'Write into Nightly check instead' })
  await expect(into).toBeVisible()
  await shot(page.locator('.composer'), '18b-composer-on-a-trigger-turn')
  await settled(page)
  await shot(page, '18b-turn-list-two-topics-and-scheduled')
  // Chosen, the line names the trigger's topic, with a way back; and back it is the user's own again.
  await into.click()
  await goesOn('Nightly check, a trigger’s topic')
  await expect(into).toHaveCount(0)
  await chat.getByRole('button', { name: `Continue ${FIRST} instead` }).click()
  await goesOn(`${FIRST}`)
  // A message written while the trigger's turn is on screen goes where the line says: the user's own topic.
  await say(page, 'hello a third time', 'Hello! Ask me to read or change a file.', 3)
  const after: { runs: { topic_id: string; unattended: boolean }[] } = await (await request.get(`/api/conversations/${conversation.id}`)).json()
  expect(after.runs.at(-1)).toMatchObject({ topic_id: snap.topics[0].id, unattended: false })
  // Written into the trigger's topic by choice, it is a turn of that topic - and the choice was for that one message.
  await openTurns(page)
  await scheduled.click()
  await into.click()
  await say(page, 'hello, nightly', 'Hello! Ask me to read or change a file.', 4)
  const last: { runs: { topic_id: string; unattended: boolean }[] } = await (await request.get(`/api/conversations/${conversation.id}`)).json()
  expect(last.runs.at(-1)).toMatchObject({ topic_id: after.runs.at(-2)!.topic_id, unattended: false })
  await goesOn(`${FIRST}`)
  await expect(chat.getByRole('button', { name: 'Write into Nightly check instead' })).toBeVisible()
})

test('in the dark theme the line above the message box and Recent stand out from what they are on (contrast 4.5 or more)', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'dark'))
  await openFreshConversation(page)
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await twoTurns(page)
  const list = page.getByRole('complementary', { name: 'Recent' })
  // (No "Continuing" line: "New topic" beside the model says in its tooltip which topic the message goes on with.)
  const line = page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'New topic' })
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  // The view takes in the whole turn.
  await expect.poll(() => holds(page.locator('.canvas-flow'), page.locator('.react-flow__node-agent').last())).toBe(true)
  // An agent's name is what its header must say: read in full, while provider · model - said again in the inspector - is cut short for it.
  const heads = page.locator('.react-flow__node-agent .node-head')
  await expect(heads.locator('.node-title')).toHaveText(['Orchestrator', 'Coder'])
  for (const title of await heads.locator('.node-title').all()) expect(await readInFull(title)).toBe(true)
  await expect(heads.last().locator('.node-names')).toHaveAttribute('title', /^Coder · Local · /)
  await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
  await settled(page)
  await shot(page, '18b-canvas-topic-dark')

  const check = async (root: Locator, least: number) => {
    const pieces = await root.evaluate(contrasts)
    expect(pieces.length).toBeGreaterThanOrEqual(least)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    return pieces
  }
  // The line in both its states.
  await check(line, 1)
  // The work line under an answer (slice 107), shut and with its details open.
  const work = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'What it did' }).first()
  await check(work, 2)
  await work.getByRole('button', { name: 'details ▸' }).click()
  await check(work, 8)
  await line.click()
  await check(line, 1)
  await line.click()
  // A second topic, so that Recent has messages of two.
  await line.click()
  await say(page, 'hi again', 'Hello! Ask me to read or change a file.')
  await openTurns(page)
  await expect(list.locator('.turn-row')).toHaveCount(3)
  await check(list, 10)
  // The first topic's newest turn, picked.
  await list.locator('.turn-row').filter({ hasText: SECOND }).click()
  await expect(page.locator('.react-flow__node-request .node-text')).toHaveText([SECOND])
  // The Coder's node, and its window with the earlier work open.
  const coder = page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) })
  await check(coder, 3)
  await coder.locator('.node-title').click()
  await expect(page.getByRole('complementary', { name: 'Inspector' })).toContainText(/continues from the .+ message/)
  await coder.locator('.node-title').dblclick()
  const window = page.getByRole('region', { name: 'Agent window' })
  await openAgentFold(window, 'Earlier work')
  await expect(window.getByRole('group', { name: /^The .+ message$/ })).toBeVisible()
  await check(window, 8)
})
