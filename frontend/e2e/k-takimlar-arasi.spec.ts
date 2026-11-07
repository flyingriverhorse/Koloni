import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, type Page, test } from './fixtures'
import { contrasts, openFreshConversation, say, settled } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// K-takimlar-arasi + K-ortak-klasor (mockup Z): the Web app's Coder asked Backend / API for GET /api/items. One real turn
// gives a real record; the page is then handed that record with the two teams' agents, the request and the lead KOLONİ
// opened for it put in it, as the server gives them (no model plays a turn like that; k-canvas-lines does the same).
// The shared folder is real: its files are in the e2e project, read and taken in by the real server.

type Json = Record<string, unknown>
const at = '2026-10-27T14:02:00Z'
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'arasi-shots')
const B23 = path.join(os.tmpdir(), 'koloni-docs', 'b23-shots')
const B26 = path.join(os.tmpdir(), 'koloni-docs', 'b26-shots')
const WHAT = 'GET /api/items, 20 a page'

/**
 * The record of `id`'s chat with the Web app and Backend / API teams: the request at work, or `answered`. `backendFirst`:
 * Backend's lead opened before the Web app's, and again after it for the request (B-152, live).
 */
async function asked(page: Page, id: string, answered = false, backendFirst = false): Promise<Json> {
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; runs: Json[]; conversation: Json; messages: Json[] }
  const teams = (await (await page.request.get('/api/teams')).json()) as { id: string; name: string }[]
  const [web, api] = ['Web app', 'Backend / API'].map(name => teams.find(t => t.name === name)!.id)
  const [lead, run] = [snap.agents[0], { ...snap.runs[0], status: 'running', ended_at: null }]
  const L = lead.id as string
  const message = snap.messages.find(m => m.role === 'assistant')!.id
  const agent = (aid: string, role: string, parent: string, status: string, more: Json = {}) => ({
    ...lead,
    id: aid,
    role_name: role,
    name: role,
    parent_agent_id: parent,
    depth: parent === L ? 1 : 2,
    status,
    task: null,
    report: null,
    input_tokens: 9000,
    output_tokens: 900,
    ...more,
  })
  const call = (cid: string, agentId: string, name: string, status: string, args: Json, more: Json = {}) => ({
    id: cid,
    run_id: run.id,
    agent_id: agentId,
    message_id: message,
    origin: 'koloni',
    parent_call_id: null,
    outside_folder: null,
    why_asked: null,
    seq: 1,
    provider_call_id: cid,
    name,
    arguments: JSON.stringify(args),
    status,
    result: null,
    started_at: at,
    ended_at: null,
    ...more,
  })
  const record = {
    ...snap,
    runs: [run],
    conversation: { ...snap.conversation, teams_mode: 'manual', teams: [web, api].map(team_id => ({ team_id, recipe_id: null, picked_by: 'user', why: null, state: null })) },
    agents: [
      // (K-shared-bagli: the Lead was given a fact from the memory.)
      { ...lead, status: 'waiting', facts_given: ['f1'] },
      agent('wl', 'Web app lead', L, 'waiting', { tool_call_id: 'sw' }),
      agent('wc', 'Coder', 'wl', answered ? 'completed' : 'waiting'),
      agent('wt', 'Tester', 'wl', 'queued'),
      agent('bl', 'Backend / API lead', L, 'completed', { tool_call_id: 'sb' }),
      agent('bl2', 'Backend / API lead', L, answered ? 'completed' : 'waiting', {
        name: 'Backend / API lead 2',
        tool_call_id: 'sr',
        report: answered ? 'GET /api/items is in app/items.py' : null,
        task: 'Coder of the Web app team asks your team for work.\nTheir contract is in the shared folder: contracts/items-api.md (read it with read_shared).',
      }),
      agent('bc', 'Coder', 'bl2', answered ? 'completed' : 'running', { name: 'Coder 2' }),
    ],
    tool_calls: [
      call('sw', L, 'spawn_agent', 'running', { role: 'Web app lead', task: 'the page' }),
      call('q1', 'wc', 'request_work', answered ? 'succeeded' : 'running', { to: 'Backend / API', what: WHAT, contract: 'GET /api/items?page=1' }, { message_id: 'mc' }),
      call('sr', L, 'spawn_agent', answered ? 'succeeded' : 'running', { role: 'Backend / API lead', task: 'Coder of the Web app team asks…', asked_by: 'Web app' }, { parent_call_id: 'q1' }),
      // What each team wrote to the shared folder in the turn (K-shared-bagli: its card).
      ...[['ws', 'wl', 'web-app/spec.md'], ['bs', 'bc', 'backend-api/items-endpoint.md']].map(([cid, by, rel]) =>
        call(cid, by, 'write_shared', 'succeeded', { path: rel }, { result: `written: .koloni/shared/${rel} - every team reads it with read_shared` }),
      ),
    ],
  }
  const [first, ...rest] = record.agents
  return backendFirst ? { ...record, agents: [first, ...rest.filter(a => a.id === 'bl'), ...rest.filter(a => a.id !== 'bl')] } : record
}

const PLACE = path.join(PROJECT_DIR, '.koloni', 'shared')
/** A file of the shared folder, as KOLONİ writes one (header, then the words). */
function file(rel: string, by: string, words: string) {
  mkdirSync(path.dirname(path.join(PLACE, rel)), { recursive: true })
  writeFileSync(path.join(PLACE, rel), `---\nby: ${by} · turn 1 · 27 Oct 14:02 UTC\n---\n${words}\n`)
}
/** The shared folder as an earlier turn left it: a decision and the Web app's spec. */
function sharedBefore() {
  rmSync(PLACE, { recursive: true, force: true })
  rmSync(path.join(PROJECT_DIR, 'contracts'), { recursive: true, force: true })
  file('decisions/pagination.md', 'KOLONİ', '20 a page.')
  file('web-app/spec.md', 'Web app · Web app lead', 'The items page.')
  writeFileSync(path.join(PLACE, '.gitignore'), '*\n')
}

// (Sharp shots, to be looked at.)
test.use({ deviceScaleFactor: 2 })
// (The shared folder left behind would give the specs after these a card for it: K-shared-bagli's "All shared files".)
test.afterAll(() => rmSync(PLACE, { recursive: true, force: true }))

for (const theme of ['light', 'dark'] as const) {
  test(`a request between two teams is one line from frame to frame, with badges, and a card of what each shared (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    mkdirSync(SHOTS, { recursive: true })
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1600, height: 1000 })
    sharedBefore()
    const id = await openFreshConversation(page)
    await say(page, 'hello, two teams and a request', 'Hello! Ask me to read or change a file.')
    // Written in this turn: the request's contract, Backend's answer - new.
    file('contracts/items-api.md', 'Web app · Coder', 'GET /api/items?page=1 -> { items, next }')
    file('backend-api/items-endpoint.md', 'Backend / API · Coder', 'done, 3 tests')
    let record = await asked(page, id)
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()
    await expect(page.locator('.team-frame')).toHaveCount(2)
    await settled(page)

    // One line, from the Web app's frame to Backend's, at work: dashed, its label on it.
    const line = page.locator('.react-flow__edge[data-id^="ask:"]')
    await expect(line).toHaveCount(1)
    await expect(page.locator('.edge-request')).toHaveText(`request · ${WHAT} · waits`)
    expect(await line.locator('path').first().evaluate(p => getComputedStyle(p).strokeDasharray)).not.toBe('none')
    // Frame edge to frame edge in the gap between them, keeping off their sides, past every box drawn.
    const geometry = await page.locator('.react-flow__edges').evaluate(() => {
      const rect = (el: Element) => el.getBoundingClientRect()
      const frames = [...document.querySelectorAll('.react-flow__node-team')].map(rect).sort((a, b) => a.y - b.y)
      const path = rect(document.querySelector('.react-flow__edge[data-id^="ask:"] path')!)
      const boxes = [...document.querySelectorAll('.react-flow__node:not(.react-flow__node-team)')].map(rect)
      const crossed = boxes.filter(b => path.x < b.right && path.right > b.x && path.y < b.bottom - 1 && path.bottom > b.y + 1).length
      return { frames: frames.map(f => [f.x, f.y, f.right, f.bottom]), path: [path.x, path.y, path.right, path.bottom], crossed }
    })
    const [[wx, , wr, wb], [ax, ay, ar]] = geometry.frames
    const [px, py, pr, pb] = geometry.path
    expect(pr - px).toBeLessThan(4) // (straight down)
    expect(Math.abs(py - wb)).toBeLessThan(3)
    expect(Math.abs(pb - ay)).toBeLessThan(10) // (its arrow's tip at Backend's top)
    for (const [left, right] of [[wx, wr], [ax, ar]]) expect(px > left + 20 && pr < right - 20).toBe(true)
    expect(geometry.crossed).toBe(0)
    // Who asked whom: on the line's label and the chat's card (the node is three lines - the user's, 5 Nov).
    await expect(page.locator('.react-flow__node[data-id="agent:wc"]')).toContainText('Waiting for Backend / API')
    // The chat's card.
    const card = page.locator('.request-card')
    await expect(card).toContainText("Web app's Coder → Backend / API")
    await expect(card).toContainText("Backend / API lead 2 gave it to its Coder · at work · Web app's Coder waits")

    // K-shared-bagli, batch-26 (the user's): a small card at each team frame's top-right, joined by one very short straight
    // line in the team's colour, level with the frame's header; everyone's beside the Lead, level with it; the contract on
    // an arm from the request's line. No fold, no close. No card on a box or another card, no line across one.
    const block = (who: string) => page.getByRole('region', { name: `${who}: shared, noted, remembered`, exact: true })
    await expect(block('Everyone')).toContainText('memory1 fact given')
    await expect(block('Web app')).toContainText('web-app/spec.md')
    await expect(block('Backend / API')).toContainText('backend-api/items-endpoint.md')
    const contract = page.getByRole('region', { name: 'A request’s contract' })
    await expect(contract).toContainText('contracts/items-api.md')
    await expect(page.locator('.shared-block').getByRole('button', { name: /^(fold|open|close|×)$/i })).toHaveCount(0)
    const lead = (record.agents as Json[])[0].id as string
    const levels = await page.locator('.react-flow__edges').evaluate((_, leadId) => {
      const rect = (el: Element) => el.getBoundingClientRect().toJSON() as DOMRect
      const frames = [...document.querySelectorAll('.react-flow__node-team')].map(el => ({ name: el.querySelector('.team-name')?.textContent, ...rect(el) }))
      const cards = [...document.querySelectorAll('.react-flow__node-shared')].map(el => ({ name: el.querySelector('section')?.getAttribute('aria-label'), ...rect(el) }))
      const boxes = [...document.querySelectorAll('.react-flow__node:not(.react-flow__node-team):not(.react-flow__node-shared)')].map(rect)
      const on = (a: DOMRect, b: DOMRect) => a.x < b.right - 1 && b.x < a.right - 1 && a.y < b.bottom - 1 && b.y < a.bottom - 1
      return {
        lead: rect(document.querySelector(`.react-flow__node[data-id="agent:${leadId}"]`)!),
        cards,
        // A card on a frame, a box or another card.
        onTop: cards.flatMap(card => [...frames, ...boxes, ...cards].filter(other => other !== card && on(card, other)).map(other => [card.name, other.x, other.y])),
        lines: [...document.querySelectorAll('.react-flow__edge[data-id^="shared:"] path.react-flow__edge-path')].map(el => {
          const line = rect(el)
          const from = frames.find(f => Math.abs(f.right - line.x) < 3 && line.y > f.y && line.y < f.bottom)
          const to = cards.find(c => Math.abs(c.x - line.right) < 3 && line.y > c.y && line.y < c.bottom)
          const crossed = [...boxes, ...frames.filter(f => f !== from), ...cards.filter(c => c !== to)].filter(b => line.x < b.right - 1 && line.right > b.x + 1 && line.y < b.bottom && line.bottom > b.y).length
          return { id: el.closest('.react-flow__edge')!.getAttribute('data-id'), box: [line.x, line.y, line.right, line.bottom], from: from && [from.name, from.y], to: to && [to.name, to.y], crossed }
        }),
      }
    }, lead)
    // Two teams' lines, the contract's arm and the Lead's to everyone's card, each straight across into its card, crossing no box or card.
    expect(levels.lines).toHaveLength(4)
    for (const { box: [x, y, right, bottom], to, crossed } of levels.lines) {
      expect(bottom - y).toBeLessThan(3)
      expect(x).toBeLessThan(right)
      expect(to).toBeTruthy()
      expect(crossed).toBe(0)
    }
    // A team's line: very short, from its own frame's right edge to its own card, whose top is level with the frame's.
    for (const name of ['Web app', 'Backend / API']) {
      const mine = levels.lines.find(one => one.from?.[0] === name)!
      expect(mine.to![0]).toBe(`${name}: shared, noted, remembered`)
      expect(mine.box[2] - mine.box[0]).toBeLessThan(40)
      expect(Math.abs(mine.to![1] - mine.from![1])).toBeLessThan(2)
      expect(mine.box[1] - mine.from![1]).toBeLessThan(40) // (in the frame's header)
    }
    expect(levels.onTop).toEqual([])
    // Everyone's beside the Lead, level with it.
    const everyone = levels.cards.find(card => card.name === 'Everyone: shared, noted, remembered')!
    expect(Math.abs(everyone.y - levels.lead.y)).toBeLessThan(2)
    expect(everyone.x).toBeGreaterThan(levels.lead.right)
    const low = async (selector: string) =>
      (await Promise.all((await page.locator(selector).all()).map(one => one.evaluate(contrasts)))).flat().filter(piece => piece.ratio < 4.5)
    for (const selector of ['.edge-request', '.react-flow__node-agent', '.shared-block', '.request-card']) expect(await low(selector), selector).toEqual([])
    // In view with the turn: none cut at the canvas's edge.
    const canvas = (await page.locator('.react-flow').boundingBox())!
    for (const node of levels.cards) {
      expect(node.x >= canvas.x && node.y >= canvas.y, node.name ?? '').toBe(true)
      expect(node.right <= canvas.x + canvas.width && node.bottom <= canvas.y + canvas.height, node.name ?? '').toBe(true)
    }
    await page.screenshot({ path: path.join(SHOTS, `request-waits-${theme}.png`) })
    mkdirSync(B26, { recursive: true })
    await page.screenshot({ path: path.join(B26, `cards-two-teams-${theme}.png`) })

    // A block's name lights its team and its line; the team's frame lights its block.
    const frame = (name: string) => page.locator('.react-flow__node-team').filter({ has: page.locator('.team-name', { hasText: name }) })
    await block('Web app').getByRole('button', { name: 'Show Web app’s line' }).click()
    await expect(frame('Backend / API')).toHaveClass(/canvas-dim/)
    await expect(frame('Web app')).not.toHaveClass(/canvas-dim/)
    await expect(page.locator('.react-flow__node-shared').filter({ has: block('Backend / API') })).toHaveClass(/canvas-faded/)
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await frame('Backend / API').locator('.team-name').click()
    await expect(page.locator('.react-flow__node-shared').filter({ has: block('Backend / API') })).not.toHaveClass(/canvas-faded/)
    await expect(page.locator('.react-flow__node-shared').filter({ has: block('Web app') })).toHaveClass(/canvas-faded/)
    // (Its own agents and block - not the team it asked through the request: N4.)
    await expect(frame('Web app')).toHaveClass(/canvas-dim/)
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    // All the shared folder's files, of every turn: the Workspace window, open at it.
    await block('Everyone').getByRole('button', { name: /^All shared files \(\d+\) →$/ }).click()
    const workspace = page.getByRole('region', { name: 'Workspace' })
    await expect(workspace.getByText('decisions', { exact: true })).toBeVisible()
    await expect(workspace.getByText('web-app', { exact: true })).toBeVisible()
    await workspace.getByRole('button', { name: /^Close/ }).first().click()

    // Take a file into the project: there, without its header; its row says so.
    await contract.getByRole('button', { name: 'Take contracts/items-api.md into the project' }).click()
    await expect(contract).toContainText('in the project as contracts/items-api.md')
    expect(readFileSync(path.join(PROJECT_DIR, 'contracts', 'items-api.md'), 'utf8')).toBe('GET /api/items?page=1 -> { items, next }\n')

    // Answered: the same line, solid, says so.
    record = await asked(page, id, true)
    await page.reload()
    await expect(page.locator('.team-frame')).toHaveCount(2)
    await settled(page)
    await expect(page.locator('.react-flow__edge[data-id^="ask:"]')).toHaveCount(1)
    await expect(page.locator('.edge-request')).toHaveText('answered ✓')
    expect(await page.locator('.react-flow__edge[data-id^="ask:"] path').first().evaluate(p => getComputedStyle(p).strokeDasharray)).toBe('none')
    await expect(card).toContainText('Backend / API lead 2 answered ✓')
    await page.screenshot({ path: path.join(SHOTS, `request-answered-${theme}.png`) })
    // A shared file is read before it is taken in: its name opens it in the Workspace window.
    await block('Backend / API').getByRole('button', { name: 'backend-api/items-endpoint.md', exact: true }).click()
    await expect(page.getByText('done, 3 tests')).toBeVisible()
  })
}

for (const theme of ['light', 'dark'] as const) {
  test(`B-152: a team opened before another and again after it keeps its frame clear of the other; the request has its line (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1600, height: 1000 })
    sharedBefore()
    const id = await openFreshConversation(page)
    await say(page, 'hello, two teams and a request', 'Hello! Ask me to read or change a file.')
    const record = await asked(page, id, true, true)
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()
    await expect(page.locator('.team-frame')).toHaveCount(2)
    await settled(page)
    const frames = await page.locator('.react-flow__node-team').evaluateAll(all => all.map(el => el.getBoundingClientRect().toJSON()))
    const [a, b] = frames
    expect(a.x < b.right && b.x < a.right && a.y < b.bottom && b.y < a.bottom).toBe(false)
    await expect(page.locator('.react-flow__edge[data-id^="ask:"]')).toHaveCount(1)
    await expect(page.locator('.edge-request')).toHaveText('answered ✓')
    await page.screenshot({ path: path.join(B23, `b152-frames-${theme}.png`) })
  })
}

test('in Workspace the shared folder shows as a folder of the project', async ({ page }) => {
  sharedBefore()
  const id = await openFreshConversation(page)
  const pid = (await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.project_id
  const listed = (await (await page.request.get(`/api/projects/${pid}/files?path=.koloni`)).json()) as { name: string; kind: string }[]
  expect(listed).toContainEqual({ name: 'shared', kind: 'dir', size: null })
})
