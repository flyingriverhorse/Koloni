import { expect, test, type APIRequestContext, type Locator, type Page } from './fixtures'
import { OWN, contrasts, freeOfChat, openAgentFold, openFreshConversation, openTurns, rail, shot, windowFromPanel } from './helpers'

const FACT = 'The service listens on port 8123.'

test.use({ viewport: { width: 1440, height: 900 } })

/** Everything in effect or waiting goes to Past: the test, and the specs after it, start from an empty memory. */
async function clearMemory(request: APIRequestContext) {
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    const memory = await (await request.get(`/api/projects/${project.id}/memory`)).json()
    const ids = new Set<string>([...memory.proposals, ...memory.core, ...memory.journal].map((r: { id: string }) => r.id))
    for (const id of ids) await request.post(`/api/memory/${id}/reject`, { headers: OWN })
  }
}

async function ask(page: Page, text: string, answers: number) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('The reviewer found no problems.')).toHaveCount(answers, { timeout: 15_000 })
}

/** Whether one node lies wholly inside another, as they are drawn (a pixel of slack: both are measured at the canvas's zoom). */
async function holds(outer: Locator, inner: Locator) {
  const [box, node] = [await outer.boundingBox(), await inner.boundingBox()]
  if (!box || !node) return false
  return (
    node.x >= box.x - 1 &&
    node.y >= box.y - 1 &&
    node.x + node.width <= box.x + box.width + 1 &&
    node.y + node.height <= box.y + box.height + 1
  )
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

/** How big a node is in the canvas's own measure, whatever the zoom. */
const size = (node: Locator) => node.evaluate(element => [(element as HTMLElement).offsetWidth, (element as HTMLElement).offsetHeight])

test.beforeEach(async ({ request }) => {
  await clearMemory(request)
})

test.afterEach(async ({ request }) => {
  await clearMemory(request)
})

test('the canvas draws one turn, picked in Recent or from the chat; what a node did is counted on it, the side panel shows it, and every node is as big as the others', async ({ page }) => {
  await openFreshConversation(page)
  const agents = page.locator('.react-flow__node-agent')
  const requests = page.locator('.react-flow__node-request .node-text')
  // (K-shared-bagli: the part memory played, a row on the card of whoever used it.)
  const memoryNodes = page.locator('.shared-row').filter({ has: page.locator('.shared-kind-memory') })
  const list = page.getByRole('complementary', { name: 'Recent' })
  const turns = list.locator('.turn-row')
  const chat = page.getByRole('region', { name: 'Chat' })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(page.getByText('No message yet. Write one to start.')).toBeVisible()

  // You write a fact into the core, about the port. The page says who will be given it.
  await rail(page, 'Memory').click()
  const core = page.getByRole('tabpanel', { name: /^Facts/ })
  await expect(core.getByText('Given to an agent when its work names the subject.')).toBeVisible()
  await core.getByRole('button', { name: '＋ Add a fact' }).click()
  const write = page.getByRole('region', { name: 'Add a fact' })
  await write.getByLabel('Fact').fill(FACT)
  await write.getByText('Subject, file and lines').click()
  await write.getByLabel('Subject').fill('port')
  await write.getByRole('button', { name: 'Add to the core' }).click()
  await expect(core.getByRole('article')).toContainText(FACT)
  await expect(core.getByRole('article')).not.toContainText('no subject')

  // Turn 1 is about something else: the greeting. Nobody is given the fact, nobody looks
  // anything up - the turn has no memory node. It is the one row of Recent.
  await rail(page, 'Canvas').click()
  await ask(page, 'review the greeting', 1)
  // The work line under its answer stands out from what it is on (slice 107), in this theme too.
  const work = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'What it did' })
  await expect(work).toContainText('1 agent')
  expect((await work.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  await expect(agents).toHaveCount(2)
  await expect(memoryNodes).toHaveCount(0)
  await openTurns(page)
  await expect(turns).toHaveCount(1)
  await expect(turns).toContainText('review the greeting')
  // (its work: the Reviewer it opened - the Lead is not counted)
  await expect(turns).toContainText('1 agent')
  await expect(turns).toContainText('done')

  // Turn 2 names the fact's subject, in the request and in the Reviewer's task: both are
  // given it, which its card says. The canvas draws this turn and nothing of the first: one
  // request, two agents, and the lines of this turn only (the request, the hand-off, the
  // Reviewer's to its card, and the Lead's to its card beside it).
  await ask(page, 'review the port of hello.py', 2)
  await openTurns(page)
  await expect(turns).toHaveCount(2)
  await expect(turns.first()).toHaveAttribute('aria-current', 'true')
  await expect(requests).toHaveText(['review the port of hello.py'])
  await expect(agents).toHaveCount(2)
  await expect(memoryNodes).toHaveText(['memory1 fact given', 'memory1 fact given'])
  const ownLines = page.locator('.react-flow__edge')
  await expect(ownLines).toHaveCount(4)
  await expect.poll(() => overlapping(page)).toEqual([])

  // Picked in the list, the first turn is drawn in its place, as it was: no memory node.
  await openTurns(page)
  await turns.last().click()
  await openTurns(page)
  await expect(turns.last()).toHaveAttribute('aria-current', 'true')
  await expect(turns.first()).not.toHaveAttribute('aria-current', 'true')
  await expect(requests).toHaveText(['review the greeting'])
  await expect(agents).toHaveCount(2)
  await expect(memoryNodes).toHaveCount(0)
  await expect(ownLines).toHaveCount(2)
  await expect.poll(() => overlapping(page)).toEqual([])
  // It is fitted: the whole turn is in sight.
  const stage = page.locator('.canvas-flow')
  await expect.poll(() => holds(stage, agents.first())).toBe(true)
  await expect.poll(() => holds(stage, agents.last())).toBe(true)
  await openTurns(page)
  await turns.first().click()
  await expect(requests).toHaveText(['review the port of hello.py'])

  // Selected from the chat, the first turn's Reviewer is in another turn: the canvas goes to
  // that turn, and to the node, which shows as the selected one - in the middle of the canvas.
  await chat.getByRole('button', { name: /Reviewer Review hello\.py/ }).first().click()
  await openTurns(page)
  await expect(turns.last()).toHaveAttribute('aria-current', 'true')
  await expect(requests).toHaveText(['review the greeting'])
  await expect(agents.locator('.node-selected')).toHaveCount(1)
  await expect(agents.locator('.node-selected')).toContainText('Reviewer')
  await expect
    .poll(async () => {
      // (the middle of what the chat leaves free)
      const [around, node] = [await freeOfChat(page), (await agents.locator('.node-selected').boundingBox())!]
      return Math.round(Math.hypot(node.x + node.width / 2 - (around.x + around.width / 2), node.y + node.height / 2 - (around.y + around.height / 2)))
    })
    .toBeLessThan(30)
  await expect.poll(() => overlapping(page)).toEqual([])
  // Back on the latest turn by hand, the canvas stays there though the Reviewer is still selected.
  await openTurns(page)
  await turns.first().click()
  await expect(requests).toHaveText(['review the port of hello.py'])
  await inspector.getByRole('button', { name: 'Close inspector' }).click()

  // In the latest turn the Reviewer is one small node (the user's, 5 Nov): its tool counted, nothing inside it; picked,
  // the side panel's card counts it too, and its window has the call: a step of its story, and its raw step.
  const reviewer = agents.filter({ has: page.locator('.node-title', { hasText: /^Reviewer$/ }) })
  await expect(reviewer.locator('.node-body > *').last()).toHaveText('1 tool')
  await expect(page.getByRole('button', { name: /^(Expand|Collapse) / })).toHaveCount(0)
  const nodeSize = await size(reviewer)
  await reviewer.getByText('Reviewer', { exact: true }).click()
  await expect(inspector.getByText('Did', { exact: true }).locator('xpath=following-sibling::dd[1]')).toContainText('1 tool')
  await shot(page, '18a-canvas-turn-list-light')
  const own = await windowFromPanel(page)
  await expect(own.locator('.agent-story h4').first()).toHaveText('Looked around')
  await expect((await openAgentFold(own, 'Every step as recorded')).getByText('read_file hello.py')).toBeVisible()
  await own.getByRole('button', { name: 'Close agent window' }).click()

  // A third turn makes fourteen calls: the Lead's node says so, and is the size of any node. The Lead's alone - no
  // sub-agent, no file changed -, once done the last message with work is in front again (slice 107); "Show its work on
  // the canvas" in its ⋯ in the chat draws it, alone.
  await page.getByLabel('Message').fill('search fourteen times')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Searched fourteen times.')).toBeVisible({ timeout: 15_000 })
  await openTurns(page)
  await expect(turns).toHaveCount(3)
  await expect(requests).toHaveText(['review the port of hello.py'])
  await chat.locator('.msg-user', { hasText: 'search fourteen times' }).getByRole('button', { name: /^Copy, restore, show its work/ }).click()
  await page.getByRole('menuitem', { name: 'Show its work on the canvas' }).click()
  await expect(requests).toHaveText(['search fourteen times'])
  await expect(agents).toHaveCount(1)
  await expect(agents.locator('.node-body > *').last()).toHaveText('14 tools')
  expect(await size(agents)).toEqual(nodeSize)
  await expect.poll(() => overlapping(page)).toEqual([])
})

test('in the dark theme Recent and an agent’s node stand out from what they are on (contrast 4.5 or more)', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('koloni-theme', 'dark'))
  await openFreshConversation(page)
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await ask(page, 'review the greeting', 1)
  // The work line under its answer stands out from what it is on (slice 107), in this theme too.
  const work = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'What it did' })
  await expect(work).toContainText('1 agent')
  expect((await work.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  // A turn in which something waits: its row says so.
  await page.getByLabel('Message').fill('edit the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  const list = page.getByRole('complementary', { name: 'Recent' })
  await openTurns(page)
  await expect(list.locator('.turn-row').getByText('waits for you')).toBeVisible({ timeout: 15_000 })
  // (The change that waits is brought up in its own window; put away, the canvas is in sight.)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  await expect(page.getByRole('region', { name: 'Workspace' })).toHaveCount(0)
  await openTurns(page)
  await list.locator('.turn-row').filter({ hasText: 'review the greeting' }).click()
  // (The list closes on a turn picked; opened again, it is read, and closed for the panel.)
  const inList = await (await openTurns(page)).evaluate(contrasts)
  await page.keyboard.press('Escape')
  await expect(list).toHaveCount(0)
  const panel = page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Reviewer$/ }) })
  await expect(panel).toBeVisible()
  await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
  await shot(page, '18a-canvas-turn-list-dark')

  const inPanel = await panel.evaluate(contrasts)
  expect(inList.length).toBeGreaterThan(8)
  expect(inPanel.length).toBeGreaterThan(2)
  expect(inList.filter(piece => piece.ratio < 4.5)).toEqual([])
  expect(inPanel.filter(piece => piece.ratio < 4.5)).toEqual([])
  // They are the theme's dark colours, not the light ones under another name.
  expect(inPanel.find(piece => /node-title/.test(piece.cls))).toMatchObject({ color: '228,230,234' })

  // Left as it was found: the change that waits is turned down.
  await openTurns(page)
  await list.locator('.turn-row').filter({ hasText: 'edit the greeting' }).click()
  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 15_000 })
})
