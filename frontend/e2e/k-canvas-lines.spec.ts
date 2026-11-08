import { expect, type Page, test } from './fixtures'
import { contrasts, openFreshConversation, say, settled, shot } from './helpers'

// K-canvas-dili (mockup W): a team's lines on the canvas. One real turn gives a real record; the page is then handed that
// record with two teams' agents and their talk put in it (as the server gives them - no model plays a turn like that):
// Web app runs a recipe - Build (UI designer, Coder), then three reviews at once, findings back to Build (a new Coder) -
// and Backend / API has none; the two Coders talk across. Nothing leaves the machine.

type Json = Record<string, unknown>
const at = '2026-10-26T14:26:00Z'

/** The record of `id`'s chat with the two teams in its turn. */
async function twoTeams(page: Page, id: string): Promise<Json> {
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; runs: Json[]; conversation: Json }
  const [lead, run] = [snap.agents[0], { ...snap.runs[0], status: 'running', ended_at: null }]
  const agent = (aid: string, role: string, parent: string, status = 'completed') => ({
    ...lead,
    id: aid,
    role_name: role,
    name: role,
    parent_agent_id: parent,
    depth: parent === lead.id ? 1 : 2,
    status,
    task: null,
    input_tokens: 9000,
    output_tokens: 900,
  })
  const said = (mid: string, from: string, to: string, kind: string, content: string) => ({ id: mid, run_id: run.id, from_agent_id: from, to_agent_id: to, kind, content, created_at: at })
  const step = (sid: string, name: string, state: string, group = false) => ({ id: sid, name, state, round: sid === 'build' ? 1 : 0, room: false, own_check: false, left_out: [], group })
  const row = (team_id: string, team: string, recipe: string, agents: string[], steps: Json[], passes: Json[]) => ({
    team_id,
    recipe_id: null,
    picked_by: 'user',
    why: null,
    state: { run_id: run.id, team, recipe, status: 'running', why: null, steps, agents, ended_ready: false, passes },
  })
  const L = lead.id as string
  return {
    ...snap,
    runs: [run],
    conversation: {
      ...snap.conversation,
      teams_mode: 'manual',
      teams: [
        row('web', 'Web app', 'Feature', ['wl', 'ui', 'wc', 'sec', 'uir', 'cr', 'wc2', 'cr2', 'wc3'], [step('spec', 'Spec', 'done'), step('build', 'Build', 'now'), step('reviews', 'Reviews', 'done', true), step('end', 'You', 'next')], [
          { part: 'build', agents: ['ui', 'wc'] },
          { part: 'reviews', agents: ['sec', 'uir', 'cr'] },
          { part: 'build', agents: ['wc2'] },
          { part: 'reviews', agents: ['cr2'] },
          { part: 'build', agents: ['wc3'] },
        ]),
        row('api', 'Backend / API', '', ['bl', 'bc', 'bt'], [], []),
      ],
    },
    agents: [
      { ...lead, status: 'running' },
      agent('wl', 'Web lead', L, 'waiting'),
      agent('ui', 'UI designer', 'wl'),
      agent('wc', 'Coder', 'wl'),
      agent('sec', 'Security', 'wl'),
      agent('uir', 'UI review', 'wl'),
      agent('cr', 'Code review', 'wl'),
      agent('wc2', 'Coder 2', 'wl'),
      agent('cr2', 'Code review 2', 'wl'),
      agent('wc3', 'Coder 3', 'wl', 'running'),
      agent('bl', 'Backend lead', L, 'running'),
      agent('bc', 'Coder', 'bl', 'running'),
      agent('bt', 'Tester', 'bl'),
    ],
    channel_messages: [
      said('m1', 'wc', 'ui', 'message', 'What text goes on the empty list?'),
      said('m2', 'ui', 'wc', 'reply', '"Nothing counted yet."'),
      said('f1', 'uir', 'ui', 'findings', '- The empty list shows no text | kind: ui | role: UI designer'),
      said('f2', 'cr', 'wc2', 'findings', '- count() throws on an empty list | kind: code | role: Coder\n- no test for [] | kind: code | role: Coder'),
      said('f3', 'cr2', 'wc3', 'findings', '- the test of [] is skipped | kind: code | role: Coder'),
      said('m3', 'wc2', 'bc', 'message', 'What does count([]) give?'),
      said('m4', 'bc', 'wc2', 'reply', '0, and I am adding a test for it.'),
    ],
  }
}

/** Whether the box of what was said lies clear of the chat floating over the canvas. */
async function clearOfChat(page: Page) {
  const [box, chat] = [await page.getByRole('region', { name: 'What was said' }).boundingBox(), await page.locator('.chat').boundingBox()]
  return !!box && !!chat && (box.y + box.height <= chat.y || box.y >= chat.y + chat.height || box.x + box.width <= chat.x || box.x >= chat.x + chat.width)
}

const FRAMES: Record<string, string[]> = { 'team:web': ['wl', 'ui', 'wc', 'sec', 'uir', 'cr', 'wc2', 'cr2', 'wc3'], 'team:api': ['bl', 'bc', 'bt'] }

// (Sharp shots of the frames, to be looked at.)
test.use({ deviceScaleFactor: 2 })

for (const theme of ['light', 'dark'] as const) {
  test(`a team's work line, findings, talk and the line across stay in their frames, and a pick lights only its lines (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1600, height: 1000 })
    const id = await openFreshConversation(page)
    await say(page, 'hello, the canvas lines', 'Hello! Ask me to read or change a file.')
    const record = await twoTeams(page, id)
    const runId = (record.runs as Json[])[0].id as string
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()
    await expect(page.locator('.team-frame')).toHaveCount(2)
    await settled(page)

    // The user's (4 Nov): a step's earlier rounds are one line each, folded once done - two of Build, one of Reviews -
    // and the newest round's finished review a chip. Opened by their lines, every agent is drawn for what follows.
    const shut = page.locator('.node-round-button[aria-expanded="false"]')
    await expect(shut).toHaveCount(3)
    await expect(page.getByRole('button', { name: 'Code review 2: ✓' })).toBeVisible()
    await shot(page.locator('.react-flow__node-team').first(), `k-canvas-lines-rounds-${theme}`)
    while ((await shut.count()) > 0) await shut.first().click()
    await settled(page)

    // No line runs out of its frame: each line of a frame - between two of its agents, from its door, its findings arcs
    // (all Web app's) - lies in that frame.
    // (Polled: the rounds just opened may still be laid out - under load, after the canvas stood still.)
    const frameOf = (agentId: string) => Object.keys(FRAMES).find(frame => FRAMES[frame].includes(agentId))
    const inFrames = () => page.locator('.react-flow__edges').evaluate((_, frames: [string, string[]][]) => {
      const rectOf = (selector: string) => document.querySelector(selector)?.getBoundingClientRect()
      const lines = [...document.querySelectorAll('.react-flow__edge')].flatMap(edge => {
        const id = edge.getAttribute('data-id') ?? ''
        // (A frame's own end, its door: its agents' frame.)
        const ends = [...id.matchAll(/(?:agent|team:\w+):(\w+)/g)].map(m => m[1])
        const frame = id.startsWith('findings:') ? frames[0] : frames.find(([name, agents]) => ends.length === 2 && ends.every(end => agents.includes(end) || end === name.slice(5)))
        return frame ? [{ id, frame: frame[0].slice(5), line: edge.querySelector('path')!.getBoundingClientRect() }] : []
      })
      return {
        checked: lines.length,
        outside: lines.flatMap(({ id, frame, line }) => {
          const box = rectOf(`.react-flow__node[data-id$=":${frame}"].react-flow__node-team`)
          // (A line from the frame's door starts at the door, which stands on the frame's edge.)
          const door = id.startsWith('work:team:') ? 8 : 1
          return box && line.x >= box.x - door && line.y >= box.y - 1 && line.right <= box.right + 1 && line.bottom <= box.bottom + 1 ? [] : [id]
        }),
      }
    }, Object.entries(FRAMES))
    // Web app: 8 work lines from its door on, the talk, 3 findings arcs; Backend: its door's line and 2 spawn lines.
    await expect.poll(inFrames).toEqual({ checked: 15, outside: [] })
    expect(frameOf('wc2')).toBe('team:web')

    // One fork into the reviews, one join out of Build: 2 + 3 - 1 lines, not one per pair. The reviews at once stand side
    // by side (the user's, 5 Nov), under their round's line: into the two under it from the side, through the gap beside
    // them; into Code review, clear of it, from above.
    const into = page.locator('.react-flow__edge[data-id^="work:"][data-id$="agent:sec"], .react-flow__edge[data-id^="work:"][data-id$="agent:uir"], .react-flow__edge[data-id^="work:"][data-id$="agent:cr"]')
    await expect(into).toHaveCount(4)
    // (Where a line runs up or down: two points of its path one over the other.)
    const down = () =>
      into.evaluateAll(all =>
        all.map(edge => {
          const points = [...(edge.querySelector('path')!.getAttribute('d') ?? '').matchAll(/(-?[\d.]+)[ ,](-?[\d.]+)/g)].map(m => [Number(m[1]), Number(m[2])])
          const [a, b] = points.slice(-2)
          return Math.abs(a[0] - b[0]) < 0.5 && b[1] > a[1]
        }),
      )
    await expect.poll(down).toEqual([false, false, true, false])
    // The Lead goes in at each team's door.
    await expect(page.locator(`.react-flow__edge[data-id="door:${(record.agents as Json[])[0].id}>team:${runId}:web"]`)).toHaveCount(1)
    // Findings back, said on their arc; talk with its last words; the line across with its doors.
    // (In the order they were drawn: two once their rounds were opened.)
    await expect(page.locator('.edge-arc')).toHaveCount(3)
    expect((await page.locator('.edge-arc').allTextContents()).sort()).toEqual(['1 finding back', '1 finding back', '2 findings back'])
    // Two rounds of the loop: each arc back on a band of its own, its label not on another's.
    const heights = () => page.locator('.edge-arc').evaluateAll(all => new Set(all.map(label => Math.round(label.getBoundingClientRect().y))).size)
    await expect.poll(heights).toBe(3)
    // Only how many: who talked and the last words are on hover, and all of it a click away. Each pair its own colour.
    await expect(page.locator('.edge-talk').first()).toHaveText('💬 2 messages')
    await expect(page.locator('.edge-talk').first()).toHaveAttribute('title', /^\S.* ↔ \S.* · the last: "Nothing counted yet\."$/)
    const talks = page.locator('.edge-talk')
    await expect(page.locator('.edge-talk .edge-talk-dot')).toHaveCount(await talks.count())
    const pairColours = await page.locator('.edge-talk-dot').evaluateAll(all => all.map(dot => getComputedStyle(dot).backgroundColor))
    const pairs = await talks.evaluateAll(all => all.map(talk => (talk.getAttribute('title') ?? '').split(' · ')[0]))
    expect(new Set(pairColours).size).toBe(new Set(pairs).size)
    // (The line across has no doors: agent to agent, by the frames' sides - the user's, 5 Nov.)
    await expect(page.locator('.edge-door')).toHaveCount(0)
    await shot(page, `k-canvas-lines-${theme}`)
    await shot(page.locator('.react-flow__node-team').first(), `k-canvas-lines-web-${theme}`)
    const low = async (selector: string) =>
      (await Promise.all((await page.locator(selector).all()).map(one => one.evaluate(contrasts)))).flat().filter(piece => piece.ratio < 4.5)
    for (const selector of ['.edge-talk', '.edge-arc', '.team-head']) expect(await low(selector), selector).toEqual([])

    // A pick: only Coder 2's lines stay, the rest fade; who said what is shown; the empty canvas brings all back.
    await page.locator('.react-flow__node[data-id="agent:wc2"] .node-head').click()
    const said = page.getByRole('region', { name: 'What was said' })
    await expect(said).toContainText('0, and I am adding a test for it.')
    expect(await page.locator('.react-flow__edge.edge-faded').count()).toBeGreaterThan(0)
    const lit = await page.locator('.react-flow__edge.edge-lit').evaluateAll(all => all.map(edge => edge.getAttribute('data-id')))
    // Its findings in, its work on to the second review, and its talk across to Backend's Coder.
    expect(lit.sort()).toEqual(['findings:f2', 'talk:agent:wc2>agent:bc', 'work:agent:wc2>agent:cr2'])
    await expect(page.locator('.react-flow__node-agent.canvas-faded').filter({ hasText: 'Security' })).toHaveCount(1)
    expect(await low('.canvas-said')).toEqual([])
    expect(await clearOfChat(page)).toBe(true)
    await shot(page, `k-canvas-lines-focus-${theme}`)
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await expect(page.locator('.react-flow__edge.edge-faded')).toHaveCount(0)
    await expect(said).toHaveCount(0)

    // A talk line's words open who said what on it.
    await page.locator('.edge-talk').first().click()
    await expect(said).toContainText('What text goes on the empty list?')
    // Its X puts it away, and every line comes back.
    await said.getByRole('button', { name: 'Close what was said' }).click()
    await expect(said).toHaveCount(0)
    await expect(page.locator('.react-flow__edge.edge-faded')).toHaveCount(0)

    // R52: Fold all folds every team's frame to its line; Open all opens them again. It sits in the corner, left of the
    // canvas's controls, not over the work.
    const [fold, controls] = await Promise.all([page.getByRole('button', { name: 'Fold all' }).boundingBox(), page.locator('.react-flow__controls').boundingBox()])
    expect(fold!.x + fold!.width).toBeLessThanOrEqual(controls!.x)
    expect(Math.abs(fold!.y + fold!.height - (controls!.y + controls!.height))).toBeLessThan(24)
    await page.getByRole('button', { name: 'Fold all' }).click()
    await expect(page.locator('.team-frame.team-shut')).toHaveCount(2)
    await page.getByRole('button', { name: 'Open all' }).click()
    await expect(page.locator('.team-frame.team-shut')).toHaveCount(0)
  })
}

// B-101: a chat whose teams have no recipe - nothing runs them on the server - has its turn's agents framed by their
// teams' roles, on the canvas only: no Ready for you, nothing to stop. On a small window, what was said is not under the chat.
test('a chat whose teams have no recipe has its agents framed by their roles, on the canvas only', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1280, height: 720 })
  const id = await openFreshConversation(page)
  await say(page, 'hello, frames by roles', 'Hello! Ask me to read or change a file.')
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; runs: Json[]; conversation: Json }
  const teams = (await (await page.request.get('/api/teams')).json()) as { id: string; name: string; roles: string[]; lead: { name: string } }[]
  const [web, other] = [teams.find(t => t.name === 'Web app')!, teams.find(t => t.name !== 'Web app' && t.roles.some(role => !teams.find(w => w.name === 'Web app')!.roles.includes(role)))!]
  const [lead, run] = [snap.agents[0], snap.runs[0]]
  const agent = (aid: string, role: string, parent = lead.id as string) => ({ ...lead, id: aid, role_name: role, name: role, parent_agent_id: parent, depth: parent === lead.id ? 1 : 2, status: 'completed' })
  const said = (mid: string, from: string, to: string, kind: string, content: string) => ({ id: mid, run_id: run.id, from_agent_id: from, to_agent_id: to, kind, content, created_at: at })
  const theirs = other.roles.find(role => !web.roles.includes(role))!
  const record = {
    ...snap,
    conversation: { ...snap.conversation, teams_mode: 'manual', teams: [web, other].map(t => ({ team_id: t.id, recipe_id: null, picked_by: 'user', why: null })) },
    agents: [lead, agent('a1', web.lead.name), agent('a2', web.roles[0], 'a1'), agent('b1', theirs)],
    channel_messages: [said('m1', 'a2', 'a1', 'message', 'Done?'), said('m2', 'a1', 'a2', 'reply', 'Yes, ship it.')],
  }
  await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
  await page.reload()
  await expect(page.locator('.team-frame')).toHaveCount(2)
  await expect(page.locator('.team-frame').first()).toContainText('no recipe')
  await expect(page.locator('.ready-node')).toHaveCount(0)
  await expect(page.locator('.team-frame').getByRole('button', { name: /^Stop/ })).toHaveCount(0)
  await settled(page)
  await shot(page, 'k-canvas-lines-by-roles')
  await page.locator('.react-flow__node[data-id="agent:a2"] .node-head').click()
  await expect(page.getByRole('region', { name: 'What was said' })).toContainText('Yes, ship it.')
  expect(await clearOfChat(page)).toBe(true)
  await shot(page, 'k-canvas-lines-by-roles-focus')
})

// B-132: what was said opens where the chat is not, wherever the chat was put (live: at the top left, under it).
for (const [where, spot] of [['top left', { x: 0, y: 10_000 }], ['top right', { x: 10_000, y: 10_000 }]] as const) {
  test(`what was said is clear of the chat put at the ${where}`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(at => localStorage.setItem('koloni-chat-spot', JSON.stringify(at)), spot)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page)
    await say(page, 'hello, where it is said', 'Hello! Ask me to read or change a file.')
    const record = await twoTeams(page, id)
    await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
    await page.reload()
    await settled(page)
    // (Coder 2's round of Build is done: one line, opened first.)
    await page.getByRole('button', { name: 'Round 2 · Coder 2 · ✓ 1' }).click()
    await page.locator('.react-flow__node[data-id="agent:wc2"] .node-head').click()
    await expect(page.getByRole('region', { name: 'What was said' })).toContainText('0, and I am adding a test for it.')
    expect(await clearOfChat(page)).toBe(true)
  })
}

// B-139: a recipe's team at work - Stop and Finish now in its head - has its title in its frame and its steps under it.
test('a team at work has its head in its frame: title, Stop and Finish now on one line, its steps under them', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const id = await openFreshConversation(page)
  await say(page, 'hello, the head', 'Hello! Ask me to read or change a file.')
  const record = await twoTeams(page, id)
  await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
  await page.reload()
  await settled(page)
  const frame = page.locator('.team-frame').first()
  await expect(frame.getByRole('button', { name: 'Finish Web app now' })).toBeVisible()
  const [box, title, steps] = await Promise.all([frame.boundingBox(), frame.locator('.team-title').boundingBox(), frame.locator('.team-steps').boundingBox()])
  const parts = await frame.locator('.team-title > *').evaluateAll(all => all.map(one => one.getBoundingClientRect().right))
  expect(Math.max(...parts)).toBeLessThanOrEqual(box!.x + box!.width + 0.5)
  expect(steps!.y).toBeGreaterThanOrEqual(title!.y + title!.height - 0.5)
  // Each step on the one line of them.
  const tops = await frame.locator('.team-step').evaluateAll(all => all.map(one => Math.round(one.getBoundingClientRect().top)))
  expect(new Set(tops).size).toBe(1)
})

// B-133: in a chat with no teams, two agents' talk is the same bubble - its count, its pair's colour, a click on it.
test('talk between agents of no team is a bubble too, and a pick shows what was said', async ({ page }) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const id = await openFreshConversation(page)
  await say(page, 'hello, no teams', 'Hello! Ask me to read or change a file.')
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Json & { agents: Json[]; runs: Json[]; conversation: Json }
  const [lead, run] = [snap.agents[0], snap.runs[0]]
  const agent = (aid: string, role: string) => ({ ...lead, id: aid, role_name: role, name: role, parent_agent_id: lead.id, depth: 1, status: 'completed', task: 'its part' })
  const said = (mid: string, from: string, to: string, kind: string, content: string) => ({ id: mid, run_id: run.id, from_agent_id: from, to_agent_id: to, kind, content, created_at: at })
  const record = {
    ...snap,
    conversation: { ...snap.conversation, teams_mode: 'none', teams: [] },
    agents: [lead, agent('c1', 'Coder'), agent('t1', 'Tester')],
    channel_messages: [said('m1', 'c1', 't1', 'message', 'Does it pass?'), said('m2', 't1', 'c1', 'reply', 'All green.')],
  }
  await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
  await page.reload()
  await settled(page)
  const bubble = page.locator('.edge-talk')
  await expect(bubble).toHaveCount(1)
  await expect(bubble).toHaveText('💬 2')
  await expect(bubble).toHaveAttribute('title', /^Coder ↔ Tester · the last: All green\.$|^Tester ↔ Coder · the last: All green\.$/)
  await expect(bubble.locator('.edge-talk-dot')).toHaveCount(1)
  await bubble.click()
  const box = page.getByRole('region', { name: 'What was said' })
  await expect(box).toContainText('Does it pass?')
  await box.getByRole('button', { name: 'Close what was said' }).click()
  await page.locator('.react-flow__node[data-id="agent:c1"]').click()
  await expect(page.getByRole('region', { name: 'What was said' })).toContainText('All green.')
  // The user's (6 Nov): it opens on the canvas's right, under the Teams button and above the buttons at its foot; its
  // head drags it - not the canvas.
  const [put, teams, buttons, flow] = await Promise.all(['.canvas-said', '.chat-teams', '.react-flow__controls', '.react-flow'].map(one => page.locator(one).boundingBox()))
  expect(put!.x + put!.width).toBeGreaterThan(flow!.x + flow!.width / 2)
  expect(put!.y).toBeGreaterThanOrEqual(teams!.y + teams!.height)
  expect(put!.y + put!.height).toBeLessThanOrEqual(buttons!.y)
  await settled(page)
  const view = await page.locator('.react-flow__viewport').getAttribute('style')
  await page.mouse.move(put!.x + 120, put!.y + 12)
  await page.mouse.down()
  await page.mouse.move(put!.x - 180, put!.y + 112, { steps: 5 })
  await page.mouse.up()
  const moved = await page.locator('.canvas-said').boundingBox()
  expect([Math.round(moved!.x - put!.x), Math.round(moved!.y - put!.y)]).toEqual([-300, 100])
  await settled(page)
  expect(await page.locator('.react-flow__viewport').getAttribute('style')).toBe(view)
  await expect(page.getByRole('region', { name: 'What was said' })).toBeVisible()
})
