import { expect, test } from 'vitest'
import type { Attachment, ChannelMessage, ChatTeam, ChatTeamState, Discussion, Room, Team } from '../api/types'
import { agent, command, conversation, convState, note, run, toolCall, userMessage } from '../test-fixtures'
import { type AgentData, type RoundData, type TeamData, deriveGraph } from './deriveGraph'
import { foldGraph, unfold } from './foldGraph'
import { ARC_ROOM, ARC_STEP, DOOR_PAD, IN_GAP, NODE_H, NODE_W, ROUND_H, ROW_GAP, TEAM_HEAD, TEAM_PAD, arcPath, arcWay, arced, crossTalk, crosses, frameLine, headOf, laneLegs, wallsOf, layoutGraph, memberLine } from './layout'

// K-canvas-dili (mockup W): a team's work line left to right in its recipe's order, one fork into a step and one join
// out of it, findings back, talk with its last words, a door for the Lead and doors between frames - no line out of a frame.

const at = '2026-10-05T10:00:00Z'
const said = (id: string, from: string, to: string, kind: ChannelMessage['kind'], content: string): ChannelMessage => ({
  id,
  run_id: 'r',
  from_agent_id: from,
  to_agent_id: to,
  kind,
  content,
  created_at: '2026-10-05T10:00:00Z',
})
const step = (id: string, name: string, state: 'done' | 'now' | 'next', group = false) => ({ id, name, state, round: 0, room: false, own_check: false, left_out: [], group })
const row = (team_id: string, team: string, agents: string[], passes: ChatTeamState['passes'], steps: ChatTeamState['steps']): ChatTeam => ({
  team_id,
  recipe_id: null,
  no_recipe: false,
  picked_by: 'user',
  why: null,
  state: { run_id: 'r', team, recipe: 'Feature', status: 'running', why: null, steps, agents, ended_ready: false, passes },
})
const sub = (id: string, role: string, parent = 'r', status: 'running' | 'completed' = 'completed') =>
  agent('r', status, { id, role_name: role, name: role, parent_agent_id: parent, depth: parent === 'r' ? 1 : 2 })

// Web app: Spec, then Build (UI designer and Coder), then Reviews at once (Security, Code review); findings sent it back
// to Build once (a new Coder), and Reviews again (a new Code review).
const STEPS = [step('spec', 'Spec', 'done'), step('build', 'Build', 'now'), step('reviews', 'Reviews', 'next', true), step('end', 'You', 'next')]
const PASSES = [
  { part: 'spec', agents: ['spec'] },
  { part: 'build', agents: ['ui', 'coder'] },
  { part: 'reviews', agents: ['sec', 'rev'] },
  { part: 'build', agents: ['coder2'] },
  { part: 'reviews', agents: ['rev2'] },
]
const AGENTS = ['spec', 'ui', 'coder', 'sec', 'rev', 'coder2', 'rev2']
const web = (more: Parameters<typeof convState>[0] = {}) =>
  convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', AGENTS, PASSES, STEPS)] },
    runs: [run('r')],
    agents: [agent('r'), sub('spec', 'Spec writer'), sub('ui', 'UI designer'), sub('coder', 'Coder'), sub('sec', 'Security'), sub('rev', 'Code review'), sub('coder2', 'Coder', 'r', 'running'), sub('rev2', 'Code review')],
    channelMessages: [
      said('m1', 'coder', 'ui', 'message', 'What text goes on the empty list?'),
      said('m2', 'ui', 'coder', 'reply', '"Nothing counted yet."'),
      said('f1', 'rev', 'coder2', 'findings', '- count() throws on an empty list | kind: code | role: Coder'),
    ],
    ...more,
  })
// The earlier round of Build and of Reviews: one line each, folded once done; opened by hand.
const [BUILD_1, REVIEWS_1] = ['round:team:r:web:build:0', 'round:team:r:web:reviews:0']
const OPENED = { [BUILD_1]: true, [REVIEWS_1]: true }
const work = (g: ReturnType<typeof deriveGraph>) => g.edges.filter(e => e.work).map(e => `${e.source}>${e.target}`)

test('the work line goes step by step: one fork into a step, one join out of it, no line per agent, none back', () => {
  const g = deriveGraph(web())
  expect(work(g)).toEqual([
    // From the frame's door to the first step.
    'team:r:web>agent:spec',
    'agent:spec>agent:ui',
    'agent:spec>agent:coder',
    // Build (2) to Reviews (2): three lines, not four - from the first of Build to each review, and the rest to the first.
    'agent:ui>agent:sec',
    'agent:ui>agent:rev',
    'agent:coder>agent:sec',
    // Back to Build is no work line (its findings are); round 2 on to Reviews again.
    'agent:coder2>agent:rev2',
  ])
  // The Lead reaches the team at its door, and draws no spawn line into the frame.
  expect(g.edges.filter(e => e.door).map(e => `${e.source}>${e.target}`)).toEqual(['agent:r>team:r:web'])
  expect(g.edges.some(e => e.spawn)).toBe(false)
  // A line flows while the agent it goes to is at work: the one to a review that is done does not.
  expect(g.edges.find(e => e.id === 'work:agent:coder2>agent:rev2')?.active).toBe(false)
  // Laid out a column a step - Reviews, a group, a dashed box - the passes of a step one under the other: each earlier
  // one a round, led by its line.
  expect((g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData).columns).toEqual([
    { ids: ['agent:spec'], atOnce: false },
    { ids: [BUILD_1, 'agent:ui', 'agent:coder', 'agent:coder2'], atOnce: false, rounds: [[BUILD_1, 'agent:ui', 'agent:coder'], ['agent:coder2']] },
    { ids: [REVIEWS_1, 'agent:sec', 'agent:rev', 'agent:rev2'], atOnce: true, rounds: [[REVIEWS_1, 'agent:sec', 'agent:rev'], ['agent:rev2']] },
  ])
})

test('talk in a team is a line of its own between the two, with the last thing said and how many; findings their own line', () => {
  const g = deriveGraph(web())
  expect(g.edges.find(e => e.talk && e.messages)).toMatchObject({ source: 'agent:coder', target: 'agent:ui', messages: 2, last: '"Nothing counted yet."' })
  expect(g.edges.find(e => e.findings !== undefined)).toMatchObject({ source: 'agent:rev', target: 'agent:coder2', findings: 1 })
})

test('laid out by its work line: a column a step, left to right, inside the frame - and room for the findings arc', () => {
  const g = foldGraph(deriveGraph(web()), OPENED)
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const x = (id: string) => positions[`agent:${id}`].x
  expect(x('spec')).toBeLessThan(x('ui'))
  // (A round's agents two to a row.)
  expect([x('coder'), x('coder2')]).toEqual([x('ui') + NODE_W + ROW_GAP, x('ui')])
  expect(x('coder')).toBeLessThan(x('sec'))
  expect([x('rev'), x('rev2')]).toEqual([x('sec') + NODE_W + ROW_GAP, x('sec')])
  const frame = { ...positions['team:r:web'], ...sizes['team:r:web'] }
  for (const id of AGENTS) {
    const [at, size] = [positions[`agent:${id}`], sizes[`agent:${id}`]]
    expect(at.x).toBeGreaterThan(frame.x)
    expect(at.x + size.width).toBeLessThan(frame.x + frame.width)
    expect(at.y).toBeGreaterThanOrEqual(frame.y + TEAM_HEAD + ARC_ROOM)
    expect(at.y + size.height).toBeLessThanOrEqual(frame.y + frame.height - ARC_ROOM)
  }
})

test('a row from before, with no passes, is laid out as a tree; its door line still goes in at the door', () => {
  const state = web()
  state.conversation.teams[0].state!.passes = []
  const g = deriveGraph(state)
  expect(work(g)).toEqual(AGENTS.map(id => `team:r:web>agent:${id}`))
  expect((g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData).columns).toEqual([])
})

test('no line runs out of a frame: the note of an agent in it is its team’s line to its card, the Lead’s talk is on the door line', () => {
  const g = deriveGraph(
    web({
      boardPosts: [note('n1', 'r', { agent_id: 'coder' })],
      channelMessages: [said('m3', 'r', 'coder', 'message', 'How far is it?'), said('m4', 'coder', 'r', 'reply', 'Half way.')],
    }),
  )
  const frame = (id: string) => g.nodes.find(n => n.id === id)?.team
  for (const e of g.edges) {
    const ends = [e.source, e.target]
    if (ends.some(id => id.startsWith('team:'))) continue
    expect(frame(e.source), e.id).toBe(frame(e.target))
  }
  expect(g.edges.filter(e => e.shared).map(e => e.source)).toEqual(['team:r:web'])
  expect(g.edges.find(e => e.door)).toMatchObject({ messages: 2, last: 'Half way.' })
})

test('talk between two teams is a line across, agent to agent, with room between their frames', () => {
  const backend = row('api', 'Backend', ['bl', 'bc'], [], [])
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['wl', 'wc'], [{ part: 'build', agents: ['wc'] }], [step('build', 'Build', 'now')]), backend] },
    runs: [run('r')],
    agents: [agent('r'), sub('wl', 'Web app lead'), sub('wc', 'Coder', 'wl'), sub('bl', 'Backend lead'), sub('bc', 'Coder', 'bl')],
    channelMessages: [said('m1', 'wc', 'bc', 'message', 'count([]) gives?'), said('m2', 'bc', 'wc', 'reply', '0')],
  })
  const g = deriveGraph(state)
  expect(g.edges.find(e => e.cross)).toMatchObject({ source: 'agent:wc', target: 'agent:bc', messages: 2, last: '0' })
  // Each team behind its own door, its lead first: the Web app lead's line to its Coder is the work line.
  expect(g.edges.filter(e => e.door).map(e => e.target)).toEqual(['team:r:web', 'team:r:api'])
  expect(work(g)).toEqual(['team:r:web>agent:wl', 'agent:wl>agent:wc', 'team:r:api>agent:bl'])
  // Backend has no recipe: its lead hands its Coder the work by its spawn line, inside its frame.
  expect(g.edges.filter(e => e.spawn).map(e => e.id)).toEqual(['agent:bl>agent:bc'])
  // Laid out one under the other, room between them for the line across and its label.
  const { positions, sizes } = layoutGraph(foldGraph(g, {}).nodes, g.edges)
  expect(positions['team:r:api'].y - (positions['team:r:web'].y + sizes['team:r:web'].height)).toBeGreaterThanOrEqual(40)
})

test('an agent opened in a frame laid out by its work line but not in it - one the user declined - is laid out apart, over nothing', () => {
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['wl', 'wc'], [{ part: 'build', agents: ['wc'] }], [step('build', 'Build', 'now')])] },
    runs: [run('r')],
    messages: [],
    agents: [agent('r'), sub('wl', 'Web app lead'), sub('wc', 'Coder', 'wl'), agent('r', 'rejected', { id: 'no', role_name: 'Tester', parent_agent_id: 'wl', depth: 2 })],
  })
  const g = foldGraph(deriveGraph(state), {})
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: 220, height: 104 }) })
  const declined = box('agent:no')
  expect(declined.x).toBeGreaterThan(0)
  for (const other of g.nodes.filter(n => !n.parent && n.id !== 'agent:no').map(n => box(n.id)))
    expect(declined.y >= other.y + other.height || declined.y + declined.height <= other.y || declined.x >= other.x + other.width || declined.x + declined.width <= other.x).toBe(true)
})

// Two teams, each with its lead and one agent - the Lead outside both.
const twoTeams = (more: Parameters<typeof convState>[0] = {}) =>
  convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['wl', 'wc'], [{ part: 'build', agents: ['wc'] }], [step('build', 'Build', 'now')]), row('api', 'Backend', ['bl', 'bc'], [], [])] },
    runs: [run('r')],
    messages: [userMessage('r', 'both, please')],
    agents: [agent('r'), sub('wl', 'Web app lead'), sub('wc', 'Coder', 'wl'), sub('bl', 'Backend lead'), sub('bc', 'Coder', 'bl'), sub('qa', 'Tester')],
    ...more,
  })
const ways = (g: ReturnType<typeof deriveGraph>, pick: (e: ReturnType<typeof deriveGraph>['edges'][number]) => unknown) =>
  g.edges.filter(pick).map(e => `${e.source}>${e.target}`)

test('a file handed to a frame’s agents comes in at its door - one line, not dropped', () => {
  const given = { id: 'f', conversation_id: 'c', message_id: 'u-r', frame_of: null, name: 'spec.md', kind: 'text', mime: 'text/plain', size: 10, summary: '1 line', given_to: ['wl', 'wc'], shown_to: {}, keep_in_project: false, created_at: at } as unknown as Attachment
  const g = deriveGraph(twoTeams({ attachments: [given] }))
  expect(ways(g, e => e.handed)).toEqual(['attachment:f>team:r:web'])
})

test('discussions between teams stand in one lane left of Ready for you, in the order they began, joined by lines through no box', () => {
  // (Live, 4 Nov: by its opener its lines ran through the other frames; then past Ready with no lines - the user wanted
  // them left of Ready, joined by lines.)
  const talk = (id: string, created_at: string, members: string[]) =>
    ({ id, run_id: 'r', agent_id: 'r', tool_call_id: 'x', topic: 'One API?', status: 'ended', outcome: 'agreed', round: 1, max_rounds: 3, created_at, ended_at: created_at, members: members.map(agent_id => ({ agent_id, status: 'in' as const, opened_here: false })) }) as unknown as Discussion
  // (The later one first in the records.)
  const g = foldGraph(deriveGraph(twoTeams({ discussions: [talk('late', '2026-10-05T11:00:00Z', ['r', 'bc']), talk('d', at, ['wc', 'bc'])] })), {})
  // Each member's line keeps its agent, to light it when the discussion is picked; it is drawn from the agent's frame.
  expect(ways(g, e => e.target === 'discussion:d')).toEqual(['agent:wc>discussion:d', 'agent:bc>discussion:d'])
  expect(g.edges.filter(e => e.target.startsWith('discussion:')).every(e => e.member)).toBe(true)
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) })
  const [first, second, ready] = [box('discussion:d'), box('discussion:late'), box(g.nodes.find(n => n.kind === 'ready')!.id)]
  expect(second).toEqual({ ...first, y: first.y + NODE_H + ROW_GAP })
  // Left of Ready, under the height its lines come in at; right of the rest - the frames and their cards.
  expect(first.x + first.width).toBeLessThan(ready.x)
  expect(first.y).toBeGreaterThan(ready.y + 24)
  const rest = g.nodes.filter(n => !n.parent && n.kind !== 'discussion' && n.kind !== 'ready')
  for (const n of rest) expect(box(n.id).x + box(n.id).width).toBeLessThan(first.x - DOOR_PAD)
  // The lines: from a frame's right edge (the Lead's, over the turn), down the gap, in at the discussion's head - over no box.
  const above = Math.min(...g.nodes.filter(n => !n.parent).map(n => box(n.id).y)) - DOOR_PAD / 2
  const boxes = g.nodes.filter(n => !n.parent).map(n => box(n.id))
  for (const e of g.edges.filter(e => e.member)) {
    const frame = g.nodes.find(n => n.id === e.source)?.team
    const points = memberLine(box(frame ?? e.source), !!frame, box(e.target), above)
    expect(points.at(-1)).toEqual({ x: box(e.target).x, y: box(e.target).y + 20 })
    for (const [a, b] of points.slice(1).map((p, i) => [points[i], p])) expect(crosses({ x1: a.x, y1: a.y, x2: b.x, y2: b.y }, boxes), e.id).toBe(false)
  }
  // A folded frame stands for its member.
  const folded = foldGraph(deriveGraph(twoTeams({ discussions: [talk('d', at, ['wc', 'bc'])] })), { 'team:r:web': false })
  expect(ways(folded, e => e.target === 'discussion:d')).toEqual(['team:r:web>discussion:d', 'agent:bc>discussion:d'])
})

test('a room the Lead opened with two teams’ leads stands in the lane, out of both frames; a room of one team’s stays in its frame', () => {
  // (Live, 5 Nov: the Orchestrator's room with the Web app and Docs leads was drawn in Web app's frame, by its first
  // member, and the Docs lead's line to it ran frame to frame from a corner - B-392 - beside their own 💬 line.)
  const room = (id: string, members: string[]) =>
    ({ id, run_id: 'r', agent_id: 'r', goal: 'One API?', status: 'working', outcome: null, why: null, members: members.map(agent_id => ({ agent_id, role: 'Lead', status: 'in' })) }) as unknown as Room
  const talked = [said('m1', 'wl', 'bl', 'message', 'One API?'), said('m2', 'bl', 'wl', 'reply', 'Yes.')]
  const g = foldGraph(deriveGraph(twoTeams({ rooms: [room('o', ['wl', 'bl']), room('p', ['wl', 'wc'])], channelMessages: talked })), {})
  expect(g.nodes.find(n => n.id === 'room:o')?.team).toBeUndefined()
  expect(g.nodes.find(n => n.id === 'room:p')?.team).toBe('team:r:web')
  // Its members' lines run from their frames to the lane; no grey line frame to frame - the leads' talk is the one across.
  expect(ways(g, e => e.target === 'room:o' && e.member)).toEqual(['agent:wl>room:o', 'agent:bl>room:o'])
  expect(ways(g, e => e.talk && !e.messages && !e.member && g.nodes.find(n => n.id === e.source)?.kind === 'team')).toEqual([])
  expect(ways(g, e => e.cross)).toEqual(['agent:wl>agent:bl'])
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const ready = positions[g.nodes.find(n => n.kind === 'ready')!.id]
  expect(positions['room:o'].x).toBeLessThan(ready.x)
  for (const frame of ['team:r:web', 'team:r:api']) expect(positions['room:o'].x).toBeGreaterThan(positions[frame].x + sizes[frame].width)
})

test('findings from outside a frame, or from another frame, come in at its door; talk with an agent outside, too', () => {
  const g = deriveGraph(
    twoTeams({
      channelMessages: [
        said('f1', 'qa', 'wc', 'findings', '- one | kind: code | role: Coder'),
        said('f2', 'bc', 'wc', 'findings', '- two | kind: code | role: Coder\n- three | kind: code | role: Coder'),
        said('m1', 'qa', 'bc', 'message', 'Is the API up?'),
        { ...said('m2', 'bc', 'qa', 'reply', 'It is.'), created_at: '2026-10-05T10:05:00Z' },
        { ...said('m3', 'r', 'wc', 'message', 'How far?'), created_at: '2026-10-05T10:09:00Z' },
        { ...said('m4', 'wc', 'r', 'reply', 'Half way.'), created_at: '2026-10-05T10:01:00Z' },
      ],
    }),
  )
  expect(g.edges.filter(e => e.findings !== undefined).map(e => [`${e.source}>${e.target}`, e.findings])).toEqual([
    ['agent:qa>team:r:web', 1],
    ['team:r:api>team:r:web', 2],
  ])
  // The Tester is not the one that opens Backend: its talk has a line of its own to the door.
  expect(g.edges.find(e => e.source === 'agent:qa' && e.target === 'team:r:api')).toMatchObject({ messages: 2, last: 'It is.' })
  // The Lead's talk is on its door line - the newest said last, whatever the order on record.
  expect(g.edges.find(e => e.door && e.target === 'team:r:web')).toMatchObject({ messages: 2, last: 'How far?' })
})

test('talk between two a work line joins is said on that line, not on a second one the same way', () => {
  const g = deriveGraph(twoTeams({ channelMessages: [said('m1', 'wc', 'wl', 'message', 'Done?'), said('m2', 'wl', 'wc', 'reply', 'Yes.')] }))
  expect(g.edges.some(e => e.id.startsWith('talk:'))).toBe(false)
  expect(g.edges.find(e => e.id === 'work:agent:wl>agent:wc')).toMatchObject({ work: true, messages: 2, last: 'Yes.' })
})

test('two rounds of a loop: each findings arc gets a band of its own, the frame as much more room', () => {
  const state = web({ channelMessages: [said('f1', 'rev', 'coder2', 'findings', '- a | kind: code | role: Coder'), said('f2', 'rev2', 'coder3', 'findings', '- b | kind: code | role: Coder')] })
  const row = state.conversation.teams[0].state!
  row.agents = [...row.agents, 'coder3']
  row.passes = [...row.passes, { part: 'build', agents: ['coder3'] }]
  state.agents.push(sub('coder3', 'Coder', 'r', 'running'))
  // (Every round opened: each agent drawn.)
  const g = foldGraph(deriveGraph(state), { ...OPENED, 'round:team:r:web:build:1': true })
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const frame = { ...positions['team:r:web'], ...sizes['team:r:web'] }
  const lowest = Math.max(...AGENTS.concat('coder3').map(id => positions[`agent:${id}`].y + sizes[`agent:${id}`].height))
  expect(frame.y + frame.height - lowest).toBe(TEAM_PAD + ARC_ROOM + ARC_STEP)
  expect(positions['agent:spec'].y - frame.y).toBe(TEAM_HEAD + ARC_ROOM + ARC_STEP)
})

test('a discussion among one team’s agents, its frame laid out as a tree, stands at the head of that frame - frames apart', () => {
  // (Opened by the Lead, among Backend's two: the second frame.)
  const met = { id: 'd', run_id: 'r', agent_id: 'r', tool_call_id: 'x', topic: 'One API?', status: 'ended', outcome: 'agreed', round: 1, max_rounds: 3, created_at: at, ended_at: at, members: ['bl', 'bc'].map(id => ({ agent_id: id, status: 'in' as const, opened_here: false })) } as unknown as Discussion
  const state = twoTeams({ discussions: [met] })
  state.conversation.teams[0].state!.passes = []
  const g = foldGraph(deriveGraph(state), {})
  expect(g.nodes.find(n => n.id === 'discussion:d')?.team).toBe('team:r:api')
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: 220, height: NODE_H }) })
  const [web, api, talk] = [box('team:r:web'), box('team:r:api'), box('discussion:d')]
  expect(web.y + web.height).toBeLessThan(api.y)
  expect(talk.y).toBeGreaterThan(api.y)
  expect(talk.y + talk.height).toBeLessThan(api.y + api.height)
})

test('B-101: a chat whose teams have no recipe has its agents framed by their teams’ roles - on the canvas only, no Ready for you', () => {
  const team = (id: string, name: string, roles: string[], lead: string) => ({ id, name, roles, lead: { name: lead } }) as unknown as Team
  const teams = [team('web', 'Web app', ['Coder', 'UI designer'], 'Web app lead'), team('api', 'Backend', ['Coder', 'Tester'], 'Backend lead')]
  const plain = (team_id: string): ChatTeam => ({ team_id, recipe_id: null, no_recipe: false, picked_by: 'user', why: null })
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [plain('web'), plain('api')] },
    runs: [run('r', 'completed')],
    messages: [userMessage('r', 'both')],
    // (The Coder is in both teams: the chat's first has it. Its helper goes with it; the Tester is Backend's.)
    agents: [agent('r', 'completed'), sub('c', 'Coder'), sub('h', 'Explorer', 'c'), sub('t', 'Tester'), sub('x', 'Planner')],
  })
  const g = deriveGraph(state, teams)
  const frame = (id: string) => g.nodes.find(n => n.id === id)?.team
  expect([frame('agent:c'), frame('agent:h'), frame('agent:t'), frame('agent:x')]).toEqual(['team:r:web', 'team:r:web', 'team:r:api', undefined])
  const web = g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  expect([web.team, web.recipe, web.stands, web.byRoles]).toEqual(['Web app', 'no recipe', 'done', true])
  expect(g.nodes.some(n => n.kind === 'ready')).toBe(false)
  // Its Lead comes in at the door; nothing else is made up.
  expect(ways(g, e => e.door)).toEqual(['agent:r>team:r:web', 'agent:r>team:r:api'])
  // No teams: none.
  expect(deriveGraph({ ...state, conversation: { ...state.conversation, teams_mode: 'none' } }, teams).nodes.some(n => n.kind === 'team')).toBe(false)
})

test('talk with an agent in a folded frame goes to the frame’s door - added up once, however often it is folded', () => {
  const g = deriveGraph(twoTeams({ channelMessages: [said('m1', 'wc', 'bc', 'message', 'Up?'), said('m2', 'bc', 'wc', 'reply', 'Yes.'), said('m3', 'wl', 'bc', 'message', 'And?')] }))
  for (const _ of [1, 2]) {
    const folded = foldGraph(g, { 'team:r:api': false })
    expect(folded.edges.filter(e => e.messages).map(e => [`${e.source}>${e.target}`, e.messages])).toEqual([
      ['agent:wc>team:r:api', 2],
      ['agent:wl>team:r:api', 1],
    ])
  }
  // Both folded: one line between the two frames.
  expect(foldGraph(g, { 'team:r:api': false, 'team:r:web': false }).edges.filter(e => e.messages).map(e => [`${e.source}>${e.target}`, e.messages])).toEqual([['team:r:web>team:r:api', 3]])
})

test('the user’s (4 Nov): a step’s earlier round is one line once done - real counts, every line of it drawn to it -, opened in place; the newest round’s finished agents chips', () => {
  const state = web()
  const finding = (blocking: boolean) => ({ what: 'x', kind: 'code' as const, role: 'Coder', blocking })
  const has = (id: string, findings: ReturnType<typeof finding>[]) => Object.assign(state.agents.find(a => a.id === id)!, { findings })
  has('sec', [])
  has('rev', [finding(true), finding(false)])
  has('rev2', [finding(true)])
  const g = deriveGraph(state)
  // What the lines say: who built it and how many finished; a review's how many reviewed and blocking - no suggestion.
  const data = (id: string) => g.nodes.find(n => n.id === id)!.data as RoundData
  expect([data(BUILD_1).said, data(BUILD_1).result]).toEqual(['Round 1 · UI designer, Coder', '✓ 2'])
  expect([data(REVIEWS_1).said, data(REVIEWS_1).result]).toEqual(['Round 1 · 2 reviewed', '1 blocking'])
  // Done, a round folds; its agents and the talk inside it are not drawn, and its lines go to its line - one of a kind.
  const folded = foldGraph(g, {})
  const ids = folded.nodes.map(n => n.id)
  expect(ids).toEqual(expect.arrayContaining([BUILD_1, REVIEWS_1, 'agent:coder2', 'agent:rev2']))
  for (const id of ['agent:ui', 'agent:coder', 'agent:sec', 'agent:rev']) expect(ids).not.toContain(id)
  expect(work(folded)).toEqual(['team:r:web>agent:spec', `agent:spec>${BUILD_1}`, `${BUILD_1}>${REVIEWS_1}`, 'agent:coder2>agent:rev2'])
  expect(folded.edges.filter(e => e.findings !== undefined).map(e => [e.source, e.target, e.findings])).toEqual([[REVIEWS_1, 'agent:coder2', 1]])
  expect(folded.edges.some(e => e.talk)).toBe(false)
  // The newest round: one at work a card, one done a chip - its name and how it ended.
  const agentData = (id: string) => folded.nodes.find(n => n.id === id)!.data as AgentData
  expect(agentData('agent:coder2').chip).toBeUndefined()
  expect(agentData('agent:rev2').chip).toEqual({ said: '1 blocking', colour: 'var(--warn)' })
  // Opened by hand (or by picking one of its agents): its agents drawn again, in place.
  expect(unfold(g, {}, 'agent:rev')).toEqual({ [REVIEWS_1]: true })
  expect(foldGraph(g, { [REVIEWS_1]: true }).nodes.map(n => n.id)).toEqual(expect.arrayContaining(['agent:sec', 'agent:rev']))
  // The frame no longer grows with its rounds: folded, it is shorter than with every agent drawn.
  const height = (graph: ReturnType<typeof foldGraph>) => layoutGraph(graph.nodes, graph.edges).sizes['team:r:web'].height
  expect(height(folded)).toBeLessThan(height(foldGraph(g, OPENED)))
})

test('a step that ran once is laid out as before: no round, no chip', () => {
  const state = web()
  const row = state.conversation.teams[0].state!
  row.passes = row.passes.slice(0, 3)
  row.agents = row.agents.filter(id => id !== 'coder2' && id !== 'rev2')
  state.agents = state.agents.filter(a => a.id !== 'coder2' && a.id !== 'rev2')
  const g = foldGraph(deriveGraph(state), {})
  expect(g.nodes.some(n => n.kind === 'round' || (n.data as AgentData).chip)).toBe(false)
  expect((g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData).columns.some(c => c.rounds)).toBe(false)
})

test('K-takim-tur (R185): once its turn is over an earlier round folds - nothing in it waits for the user any more', () => {
  // Live: Round 1's reviewers stayed an open box after the run ended. A command of its Tester's still "proposed" on the
  // page (or a question still "pending") is no wait once the turn is over: nobody is left to run or ask it.
  const state = web({ runs: [run('r', 'completed')], commands: [command('k', 'r', { agent_id: 'sec', status: 'proposed' })] })
  state.agents = state.agents.map(a => (a.id === 'coder2' ? { ...a, status: 'completed' } : a))
  const g = deriveGraph(state)
  expect((g.nodes.find(n => n.id === REVIEWS_1)!.data as RoundData).attention).toBe(false)
  expect(foldGraph(g, {}).nodes.map(n => n.id)).not.toContain('agent:sec')
  // While it runs, the same command waits for the user: its round stays open.
  const live = deriveGraph(web({ commands: [command('k', 'r', { agent_id: 'sec', status: 'proposed' })] }))
  expect(foldGraph(live, {}).nodes.map(n => n.id)).toContain('agent:sec')
})

test('a round never hides an agent that waits for the user, nor one opened again for a later round; its id is its step’s', () => {
  const state = web()
  // Code review asks the user something: its round opens, though the user folded it.
  state.questions = [{ id: 'q', run_id: 'r', agent_id: 'rev', status: 'pending', question: 'Which way?' } as unknown as (typeof state.questions)[number]]
  const g = deriveGraph(state)
  expect((g.nodes.find(n => n.id === REVIEWS_1)!.data as RoundData).attention).toBe(true)
  expect(foldGraph(g, { [REVIEWS_1]: false }).nodes.map(n => n.id)).toContain('agent:rev')
  // The UI designer opened again in Build's round 2: of that round, drawn - and round 1 counts only the Coder.
  const again = web()
  // (A copy: PASSES is every test's.)
  again.conversation.teams[0].state!.passes = PASSES.map((pass, at) => (at === 3 ? { ...pass, agents: [...pass.agents, 'ui'] } : pass))
  const h = foldGraph(deriveGraph(again), {})
  expect(h.nodes.map(n => n.id)).toContain('agent:ui')
  expect((h.nodes.find(n => n.id === BUILD_1)!.data as RoundData).said).toBe('Round 1 · Coder')
})

test('the user’s (6 Nov): talk between two of a frame goes on an arc round its cards, as findings back do - never under one', () => {
  // The UI designer and the second Code review talked: a straight line between them runs under the Coder's card.
  const state = web({ channelMessages: [said('m1', 'rev2', 'ui', 'message', 'Is the empty text final?'), said('m2', 'ui', 'rev2', 'reply', 'Yes.'), said('f1', 'rev', 'coder2', 'findings', '- a | kind: code | role: Coder')] })
  const g = foldGraph(deriveGraph(state), OPENED)
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const rect = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) })
  const frameOf = (id: string) => g.nodes.find(n => n.id === id)?.team
  const cards = g.nodes.filter(n => n.team === 'team:r:web' && !n.parent && positions[n.id]).map(n => rect(n.id))
  const talk = g.edges.find(e => e.talk && e.messages)!
  expect(arced(talk)).toBe(true)
  const centre = (id: string) => ({ x: rect(id).x + rect(id).width / 2, y: rect(id).y + NODE_H / 2 })
  const [ui, rev2] = [centre('agent:ui'), centre('agent:rev2')]
  expect(crosses({ x1: ui.x, y1: ui.y, x2: rev2.x, y2: ui.y }, cards.filter(c => c !== rect('agent:ui') && c.x > rect('agent:ui').x && c.x < rect('agent:rev2').x))).toBe(true)
  // Two arcs in the frame - the talk and the findings - each on a band of its own, in the room the frame has for two.
  const arcs = g.edges.filter(arced).map(e => arcWay(e, g.nodes, g.edges, rect, frameOf))
  expect(arcs).toHaveLength(2)
  const way = arcWay(talk, g.nodes, g.edges, rect, frameOf)
  // From the end further right; under the work line - the UI designer has its earlier round's line over it and a Coder
  // under it -, in at its side.
  expect([way.source, way.target, way.into]).toEqual(['agent:rev2', 'agent:ui', 'side'])
  const frame = rect('team:r:web')
  expect(way.band).toBeGreaterThan(Math.max(...cards.map(c => c.y + c.height)))
  // Every leg of its path - out of Code review 2's right, down beside it, back under the work line, up beside the UI
  // designer's column and in - is clear of every card: it touches only its two ends' edges.
  const [s, t] = [rect(way.source), rect(way.target)]
  const path = arcPath(s.x + s.width, s.y + NODE_H / 2, t.x, t.y + NODE_H / 2, way.band, way.ring, true)
  const points = [...path.matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map(m => ({ x: Number(m[1]), y: Number(m[2]) }))
  for (const [a, b] of points.slice(1).map((p, i) => [points[i], p])) expect(crosses({ x1: a.x, y1: a.y, x2: b.x, y2: b.y }, cards), `${a.x},${a.y} ${b.x},${b.y}`).toBe(false)
  // Inside its frame.
  for (const p of points) expect(p.x > frame.x && p.x < frame.x + frame.width && p.y > frame.y && p.y < frame.y + frame.height, `${p.x},${p.y}`).toBe(true)
  // The frame keeps room for both arcs: one band more than for the findings alone.
  const alone = foldGraph(deriveGraph(web({ channelMessages: [said('f1', 'rev', 'coder2', 'findings', '- a | kind: code | role: Coder')] })), OPENED)
  const before = layoutGraph(alone.nodes, alone.edges)
  expect(positions['agent:spec'].y - frame.y - (before.positions['agent:spec'].y - before.positions['team:r:web'].y)).toBe(ARC_STEP)
})

test('B-391: a loop to itself - Evolve’s candidates - is a round a pass: each earlier one a line, the newest two side by side', () => {
  // Live, 5 Nov: Evolve's 6 Coders - three rounds of two candidates - ran down one column, off the screen.
  const coders = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6']
  const passes = [['c1', 'c2'], ['c3', 'c4'], ['c5', 'c6']].map(agents => ({ part: 'build', agents }))
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', [...coders, 'h'], passes, [{ ...step('build', 'Build', 'now'), round: 2 }, step('end', 'You', 'next')])] },
    runs: [run('r')],
    agents: [agent('r'), ...coders.map((id, i) => sub(id, i % 2 ? 'Coder 2' : 'Coder', 'r', i < 4 ? 'completed' : 'running')), sub('h', 'Helper', 'c5', 'running')],
  })
  const g = foldGraph(deriveGraph(state), {})
  const [one, two] = ['round:team:r:web:build:0', 'round:team:r:web:build:1']
  expect((g.nodes.find(n => n.id === one)!.data as RoundData).said).toBe('Round 1 · Coder, Coder 2')
  expect(g.nodes.map(n => n.id)).not.toContain('agent:c3')
  // The work line goes round to round, then into the newest's two.
  expect(work(g)).toEqual(['team:r:web>' + one, `${one}>${two}`, `${two}>agent:c5`, `${two}>agent:c6`])
  const { positions } = layoutGraph(g.nodes, g.edges)
  const [r1, r2, c5, c6, h] = [one, two, 'agent:c5', 'agent:c6', 'agent:h'].map(id => positions[id])
  expect(r2.x).toBe(r1.x)
  expect(r2.y).toBeGreaterThan(r1.y)
  expect(c5.y).toBeGreaterThan(r2.y)
  expect([c6.y, c6.x > c5.x]).toEqual([c5.y, true])
  // A helper on a row of its own under them.
  expect([h.x, h.y > c5.y]).toEqual([c5.x, true])
  // Its first round - no round before it - one under the other: side by side, the work line into the second would
  // run through the first.
  state.conversation.teams[0].state!.passes = passes.slice(0, 1)
  const first = foldGraph(deriveGraph(state), {})
  const at1 = layoutGraph(first.nodes, first.edges).positions
  expect([at1['agent:c2'].x, at1['agent:c2'].y > at1['agent:c1'].y]).toEqual([at1['agent:c1'].x, true])
})

// Evolve's Coders, round by round (5 Nov, the user's screenshots): `passes` its rounds' pairs, `round` the strip's.
const evolve = (passes: string[][], round: number, running: string[] = []) => {
  const coders = passes.flat()
  return convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', coders, passes.map(agents => ({ part: 'build', agents })), [{ ...step('build', 'Build', 'now'), round }, step('end', 'You', 'next')])] },
    runs: [run('r')],
    agents: [agent('r'), ...coders.map((id, i) => sub(id, i % 2 ? 'Coder 2' : 'Coder', 'r', running.includes(id) ? 'running' : 'completed'))],
    // The newest round's first Coder at work with its tools.
    toolCalls: running.slice(0, 1).flatMap(id => [toolCall(`t-${id}`, 'r', 'edit_file', 'succeeded', '{"path":"a.py"}', { agent_id: id }), toolCall(`u-${id}`, 'r', 'read_file', 'succeeded', '{"path":"a.py"}', { agent_id: id })]),
  })
}

test('5 Nov: Evolve between its rounds - begun, over with the next not opened, the next begun - each earlier round a line, the newest right under them inside the frame', () => {
  const [one, two] = ['round:team:r:web:build:0', 'round:team:r:web:build:1']
  for (const [passes, round, running, lines, cards] of [
    [[['c1', 'c2'], ['c3', 'c4']], 1, ['c3', 'c4'], [one], ['agent:c3', 'agent:c4']],
    // Round 2 over, round 3 on the strip, its Coders not opened yet: round 2's two are chips, still in the frame.
    [[['c1', 'c2'], ['c3', 'c4']], 2, [], [one], ['agent:c3', 'agent:c4']],
    [[['c1', 'c2'], ['c3', 'c4'], ['c5', 'c6']], 2, ['c5', 'c6'], [one, two], ['agent:c5', 'agent:c6']],
  ] as const) {
    const g = foldGraph(deriveGraph(evolve(passes.map(pass => [...pass]), round, [...running])), {})
    const drawn = g.nodes.filter(n => n.kind === 'agent' && n.team).map(n => n.id)
    expect([g.nodes.filter(n => n.kind === 'round').map(n => n.id), drawn]).toEqual([lines, cards])
    // Every line of an earlier round's agents starts at its line.
    expect(g.edges.filter(e => e.work && cards.includes(e.target as never)).map(e => e.source)).toEqual([lines[lines.length - 1], lines[lines.length - 1]])
    const { positions, sizes } = layoutGraph(g.nodes, g.edges)
    const box = (id: string) => ({ ...positions[id], ...sizes[id] })
    const [last, frame] = [box(lines[lines.length - 1]), box('team:r:web')]
    // Straight under the last line, side by side.
    for (const id of cards) expect(positions[id].y, id).toBe(last.y + ROUND_H + IN_GAP)
    // In the frame - the card at work too, as small as any (the user's, 5 Nov).
    for (const id of [...lines, ...cards]) {
      const b = box(id)
      expect(b.x >= frame.x && b.y >= frame.y && b.x + b.width <= frame.x + frame.width && b.y + b.height <= frame.y + frame.height, id).toBe(true)
    }
    if (running.length) expect(sizes[cards[0]].height).toBe(NODE_H)
  }
})

type Box = { x: number; y: number; width: number; height: number }
/** A line's points as legs, [x1, y1, x2, y2] each. */
const legsOf = (points: { x: number; y: number }[]) => points.slice(1).map((p, k) => [points[k].x, points[k].y, p.x, p.y])

/** A turn laid out as the canvas lays it out, and what no line may cross: every card (a pixel in from each edge: a leg that leaves or comes in at an edge only touches it), and every frame's header. */
function drawn(state: Parameters<typeof deriveGraph>[0], folds = {}) {
  const g = foldGraph(deriveGraph(state), folds)
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const byId = new Map(g.nodes.map(n => [n.id, n]))
  const box = (id: string): Box => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) })
  const placed = g.nodes.filter(n => !n.parent && positions[n.id])
  const cards = placed.filter(n => n.kind !== 'team')
  const frames = placed.filter(n => n.kind === 'team')
  const inset = (b: Box) => ({ x: b.x + 1, y: b.y + 1, width: b.width - 2, height: b.height - 2 })
  const walls = [...cards.map(n => ({ id: n.id, ...inset(box(n.id)) })), ...frames.map(f => ({ id: `head of ${f.id}`, ...inset(headOf(box(f.id))) }))]
  const hit = (leg: number[], but: string[] = []) => walls.filter(w => !but.includes(w.id) && crosses({ x1: leg[0], y1: leg[1], x2: leg[2], y2: leg[3] }, [w])).map(w => w.id)
  return { g, byId, box, cards, frames, hit }
}

/**
 * A frame's own lines as the canvas draws them (CanvasView `lineOf` - `frameLine`): from its door, or between two of its
 * nodes, not on an arc (those keep to their bands: `arcWay`); each as its legs.
 */
function frameLegs({ g, byId, box, cards }: ReturnType<typeof drawn>) {
  const inFrame = g.edges.filter(e => !arced(e) && byId.get(e.target)?.team && (byId.get(e.source)?.kind === 'team' || byId.get(e.source)?.team === byId.get(e.target)?.team))
  return inFrame.map(e => {
    const frame = byId.get(e.target)!.team!
    const door = byId.get(e.source)?.kind === 'team'
    const own = [...cards.filter(n => n.team === frame).map(n => box(n.id)), ...wallsOf(box(frame))]
    const { source, target, points } = frameLine(e, box, door, own)
    return { e, legs: points ? legsOf(points) : laneLegs(box(source), box(target), door).map(l => [l.x1, l.y1, l.x2, l.y2]) }
  })
}

// The user's (5 Nov): a step at once - a room and its four agents (Reviewer 2, Security, Tester, UI designer) -, the room at
// their head. Side by side, the work line forks into each from above, and the room's lines fan out to them.
const atOnce = () => {
  const room = { id: 'o', run_id: 'r', agent_id: 'wl', goal: 'Review it', status: 'working', outcome: null, why: null, members: ['rv', 'sc', 'ts', 'ux'].map(agent_id => ({ agent_id, role: 'Reviewer', status: 'in' })) } as unknown as Room
  return convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['wl', 'sp', 'cd', 'rv', 'sc', 'ts', 'ux'], [{ part: 'spec', agents: ['sp'] }, { part: 'build', agents: ['cd'] }, { part: 'reviews', agents: ['rv', 'sc', 'ts', 'ux'] }], [step('spec', 'Spec', 'done'), step('build', 'Build', 'done'), step('reviews', 'Reviews', 'now', true)])] },
    runs: [run('r')],
    agents: [agent('r'), sub('wl', 'Web app coordinator'), sub('sp', 'Spec writer', 'wl'), sub('cd', 'Coder', 'wl'), ...['rv', 'sc', 'ts', 'ux'].map(id => sub(id, id, 'wl', 'running'))],
    rooms: [room],
  })
}

test('5 Nov: no line of a frame runs under a card or over its header - nor under its own ends, but where it leaves and comes in', () => {
  const two = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['wl', 'wc'], [{ part: 'build', agents: ['wc'] }], [step('build', 'Build', 'now')]), row('api', 'Backend', ['bl', 'bc'], [], [])] },
    runs: [run('r')],
    agents: [agent('r'), sub('wl', 'Web app lead'), sub('wc', 'Coder', 'wl'), sub('bl', 'Backend lead'), sub('bc', 'Coder', 'bl')],
  })
  const three = evolve([['c1', 'c2'], ['c3', 'c4'], ['c5', 'c6']], 2, ['c5', 'c6'])
  for (const state of [three, two, atOnce()]) {
    const turn = drawn(state)
    const lines = frameLegs(turn)
    expect(lines.length).toBeGreaterThan(2)
    for (const { e, legs } of lines) for (const leg of legs) expect(turn.hit(leg), e.id).toEqual([])
    // ... and none leaves its frame (B-97): every corner in it, the door on its edge.
    for (const { e, legs } of lines) {
      const f = turn.box(turn.byId.get(e.target)!.team!)
      for (const [x, y] of legs.flatMap(leg => [leg.slice(0, 2), leg.slice(2)])) expect(x >= f.x && x <= f.x + f.width && y >= f.y && y <= f.y + f.height, `${e.id} at ${x},${y}`).toBe(true)
    }
  }
})

test('5 Nov: steps at once stand side by side, the work line into each from above, the room’s lines fanned out to them', () => {
  const turn = drawn(atOnce())
  const [rv, sc, ts, ux, room] = ['agent:rv', 'agent:sc', 'agent:ts', 'agent:ux', 'room:o'].map(turn.box)
  // Three to a row, the fourth under the first; the room at their head.
  expect([sc.y, ts.y]).toEqual([rv.y, rv.y])
  expect([sc.x > rv.x, ts.x > sc.x, ux.x, ux.y > rv.y]).toEqual([true, true, rv.x, true])
  expect(room.y + room.height).toBeLessThanOrEqual(rv.y)
  const lines = frameLegs(turn)
  // Into each of the row but the first, from above: its last leg comes down into its top.
  for (const id of ['agent:sc', 'agent:ts']) {
    const fork = lines.find(({ e }) => e.work && e.target === id)!
    const last = fork.legs[fork.legs.length - 1]
    expect([last[0], last[2], last[3] === turn.box(id).y], id).toEqual([last[2], turn.box(id).x + NODE_W / 2, true])
  }
})

// The user's screenshots (5 Nov): three teams one under the other - Web app, Data, Docs -, their agents talking across:
// the two coordinators, Data's coordinator with Docs' writer (lead and worker), and Web app's Coder with Docs' writer (past
// Data's frame). Each team's second agent is under its first in its column, so a line straight down from the first ran through
// it; `one`: none under it - each frame one row right under its header, the only way out under its row (live, 5 Nov).
const threeTeams = (one = false) => {
  const state = convState({
    conversation: {
      ...conversation,
      teams_mode: 'manual',
      teams: [
        row('web', 'Web app', ['wl', 'wc', 'wd'], [{ part: 'build', agents: ['wc', 'wd'] }], [step('build', 'Build', 'now')]),
        row('data', 'Data', ['dl', 'da', 'db'], [{ part: 'look', agents: ['da', 'db'] }], [step('look', 'Analyse', 'now')]),
        row('docs', 'Docs', ['ol', 'ow', 'ox'], [{ part: 'write', agents: ['ow', 'ox'] }], [step('write', 'Write', 'now')]),
      ],
    },
    runs: [run('r')],
    agents: [agent('r'), ...['wl', 'dl', 'ol'].map(id => sub(id, `${id} lead`)), ...[['wc', 'wl'], ['wd', 'wl'], ['da', 'dl'], ['db', 'dl'], ['ow', 'ol'], ['ox', 'ol']].map(([id, lead]) => sub(id, id, lead))],
    channelMessages: [
      said('m1', 'wl', 'dl', 'message', 'Which table?'),
      said('m2', 'dl', 'wl', 'reply', 'items.'),
      said('m3', 'dl', 'ow', 'message', 'Write it up.'),
      said('m4', 'wc', 'ow', 'message', 'The API is /api/items.'),
    ],
  })
  if (!one) return state
  const two = ['wd', 'db', 'ox']
  const teams = state.conversation.teams.map(t => ({ ...t, state: { ...t.state, agents: t.state.agents.filter(a => !two.includes(a)), passes: t.state.passes.map(p => ({ ...p, agents: p.agents.filter(a => !two.includes(a)) })) } }))
  return { ...state, conversation: { ...state.conversation, teams }, agents: state.agents.filter(a => !two.includes(a.id)) }
}

test('5 Nov: talk between agents of two frames runs agent to agent in the margin right of the frames, out of and into each by its side - through no frame, header or card', () => {
  for (const one of [false, true]) crossing(drawn(threeTeams(one)))
})

function crossing(turn: ReturnType<typeof drawn>) {
  const across = turn.g.edges.filter(e => e.cross)
  expect(across.map(e => `${e.source}>${e.target}`)).toEqual(['agent:wl>agent:dl', 'agent:dl>agent:ow', 'agent:wc>agent:ow'])
  const frames = turn.frames.map(f => turn.box(f.id))
  const right = Math.max(...frames.map(f => f.x + f.width))
  const inside = (p: number[], f: Box) => p[0] > f.x && p[0] < f.x + f.width && p[1] > f.y && p[1] < f.y + f.height
  for (const [i, e] of across.entries()) {
    const [fa, fb] = [turn.byId.get(e.source)!.team!, turn.byId.get(e.target)!.team!]
    const line = crossTalk(turn.box(e.source), turn.box(e.target), turn.box(fa), turn.box(fb), frames, turn.cards.map(n => turn.box(n.id)), i)!
    expect(line, e.id).not.toBeNull()
    const legs = legsOf(line.points)
    // Agent to agent: from its own side to the other's.
    expect(legs[0].slice(0, 2), e.id).not.toEqual(legs[legs.length - 1].slice(2))
    // Under no card but its ends, over no header, through no frame but its two.
    const others = turn.frames.filter(f => f.id !== fa && f.id !== fb).map(f => ({ id: f.id, ...turn.box(f.id) }))
    for (const leg of legs) {
      expect(turn.hit(leg, [e.source, e.target]), e.id).toEqual([])
      expect(others.filter(f => crosses({ x1: leg[0], y1: leg[1], x2: leg[2], y2: leg[3] }, [f])).map(f => f.id), e.id).toEqual([])
      // Out of its frame and into the other by a side: a leg that crosses a frame's edge is across, not up or down.
      for (const f of [turn.box(fa), turn.box(fb)]) if (inside(leg.slice(0, 2), f) !== inside(leg.slice(2), f)) expect(leg[1], e.id).toBe(leg[3])
    }
    // In the margin right of the frames, its label on it there.
    expect(Math.max(...line.points.map(p => p.x)), e.id).toBeGreaterThan(right)
    expect(line.at.x, e.id).toBeGreaterThan(right)
  }
}

test('5 Nov: Evolve with its earlier rounds opened: no line of it runs under a card or over its header', () => {
  const [one, two] = ['round:team:r:web:build:0', 'round:team:r:web:build:1']
  const turn = drawn(evolve([['c1', 'c2'], ['c3', 'c4'], ['c5', 'c6']], 2, ['c5', 'c6']), { [one]: true, [two]: true })
  const lines = frameLegs(turn)
  expect(lines.flatMap(({ e, legs }) => legs.flatMap(leg => turn.hit(leg).map(id => `${e.id} under ${id}`)))).toEqual([])
  const f = turn.box('team:r:web')
  const out = lines.flatMap(({ e, legs }) => legs.flatMap(leg => [leg.slice(0, 2), leg.slice(2)]).filter(([x, y]) => x < f.x || x > f.x + f.width || y < f.y || y > f.y + f.height).map(() => e.id))
  expect(out).toEqual([])
})
