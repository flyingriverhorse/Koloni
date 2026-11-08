import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import type { Agent, ChatTeam, Team } from '../api/types'
import { agent, conversation, convState, note, run, toolCall, userMessage } from '../test-fixtures'
import { requestsOf, standsLine } from '../agents/teamRequests'
import { type AgentData, type GraphNode, deriveGraph } from './deriveGraph'
import { foldGraph } from './foldGraph'
import { CARD_GAP, COL_GAP, NODE_H, NODE_W, REQUEST_INSET, TEAM_HEAD, blockSize, crosses, layoutGraph, requestLine } from './layout'
import type { SharedData } from './sharedColumn'
import { SharedNode } from './SharedNode'
import { useApp } from '../state/store'
import { NodeActions } from './toggleGroup'

// K-takimlar-arasi (mockup Z): a request between teams is one short line in the gap between the two frames, frame to
// frame, that never crosses a box; who asked whom is on the agents' badges.

const team = (id: string, name: string, roles: string[]) => ({ id, name, roles, lead: { name: `${name} lead` }, lead_on: true }) as unknown as Team
const TEAMS = [team('web', 'Web app', ['Coder', 'Tester', 'UI designer']), team('api', 'Backend / API', ['Coder', 'Tester'])]
const plain = (team_id: string): ChatTeam => ({ team_id, recipe_id: null, no_recipe: false, picked_by: 'user', why: null })
const sub = (id: string, role: string, parent: string, status: Agent['status'] = 'running', over: Partial<Agent> = {}) =>
  agent('r', status, { id, role_name: role, name: role, parent_agent_id: parent, depth: parent === 'r' ? 1 : 2, ...over })

/** Web app's Coder asked Backend / API for GET /api/items: KOLONİ opened Backend's lead again for it, which gave it to its Coder. */
function asked(stands: 'waits' | 'answered' | 'declined' = 'waits') {
  const done = stands !== 'waits'
  return convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [plain('web'), plain('api')] },
    runs: [run('r')],
    messages: [userMessage('r', 'the items page and its API')],
    agents: [
      agent('r', 'waiting'),
      sub('wl', 'Web app lead', 'r', 'waiting', { tool_call_id: 's1' }),
      sub('wc', 'Coder', 'wl', 'waiting', { tool_call_id: 's2' }),
      sub('wt', 'Tester', 'wl', 'queued', { tool_call_id: 's3' }),
      sub('bl', 'Backend / API lead', 'r', 'completed', { tool_call_id: 's4' }),
      sub('bl2', 'Backend / API lead', 'r', done ? 'completed' : 'waiting', {
        name: 'Backend / API lead 2',
        tool_call_id: 's6',
        report: stands === 'declined' ? 'Declined: the page reads a file' : done ? 'GET /api/items is in' : null,
      }),
      ...(stands === 'declined'
        ? []
        : [sub('bc', 'Coder', 'bl2', done ? 'completed' : 'running', { name: 'Coder 2', tool_call_id: 's7' }), sub('bu', 'UI designer', 'bc', 'completed', { depth: 3 })]),
    ],
    toolCalls: [
      toolCall('s1', 'r', 'spawn_agent', 'running'),
      toolCall('5', 'r', 'request_work', done ? 'succeeded' : 'running', JSON.stringify({ to: 'Backend / API', what: 'GET /api/items, 20 a page', contract: 'x' }), { agent_id: 'wc' }),
      toolCall('s6', 'r', 'spawn_agent', done ? 'succeeded' : 'running', JSON.stringify({ role: 'Backend / API lead', task: '…', asked_by: 'Web app' }), { parent_call_id: '5' }),
    ],
  })
}

const box = (positions: Record<string, { x: number; y: number }>, sizes: Record<string, { width: number; height: number }>, id: string) => ({
  ...positions[id],
  ...(sizes[id] ?? { width: NODE_W, height: NODE_H }),
})

test('the request is one line from the Web app’s frame to Backend’s, in the gap between them, past every box', () => {
  const g = foldGraph(deriveGraph(asked(), TEAMS), {})
  // One line, frame to frame - no second line, and none from an agent across a frame.
  const lines = g.edges.filter(e => e.request)
  expect(lines.map(e => [e.source, e.target, e.request])).toEqual([
    ['team:r:web', 'team:r:api', { label: 'request · GET /api/items, 20 a page · waits', open: true, title: expect.any(String), calls: ['5'] }],
  ])
  expect(g.edges.filter(e => e.cross || e.talk)).toEqual([])
  // The member Backend's lead opened is Backend's, though the Web app comes first and has a Coder too.
  expect(g.nodes.find(n => n.id === 'agent:bc')?.team).toBe('team:r:api')
  // ...and the helper it opened, though its role is the Web app's only.
  expect(g.nodes.find(n => n.id === 'agent:bu')?.team).toBe('team:r:api')
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const [web, api] = [box(positions, sizes, 'team:r:web'), box(positions, sizes, 'team:r:api')]
  const others = g.nodes.filter((n: GraphNode) => !n.parent && !n.id.startsWith('team:')).map(n => box(positions, sizes, n.id))
  const line = requestLine(web, api, [...others])!
  // Straight down, out of the Web app frame's foot and into Backend's top - not along either frame's edge.
  expect([line.x1, line.y1, line.x2, line.y2]).toEqual([line.x1, web.y + web.height, line.x1, api.y])
  for (const frame of [web, api]) {
    expect(line.x1).toBeGreaterThanOrEqual(frame.x + REQUEST_INSET)
    expect(line.x1).toBeLessThanOrEqual(frame.x + frame.width - REQUEST_INSET)
  }
  for (const one of [...others, web, api]) {
    const crosses = line.x1 > one.x && line.x1 < one.x + one.width && Math.max(line.y1, one.y) < Math.min(line.y2, one.y + one.height)
    expect(crosses).toBe(false)
  }
})

test('B-152: a team whose lead the Lead opened before another team’s, and again after it, keeps its frame clear of the other', () => {
  // (Live: Docs' frame grew round its two leads and over the Web app's, and the request had no line.)
  const state = asked('answered')
  const [lead, bl] = [state.agents[0], state.agents.find(a => a.id === 'bl')!]
  const agents = [lead, bl, ...state.agents.filter(a => a !== lead && a !== bl)]
  const g = foldGraph(deriveGraph({ ...state, agents }, TEAMS), {})
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const [web, api] = [box(positions, sizes, 'team:r:web'), box(positions, sizes, 'team:r:api')]
  const meet = web.x < api.x + api.width && api.x < web.x + web.width && web.y < api.y + api.height && api.y < web.y + web.height
  expect(meet).toBe(false)
  const others = g.nodes.filter((n: GraphNode) => !n.parent && !n.id.startsWith('team:')).map(n => box(positions, sizes, n.id))
  expect(requestLine(api, web, others)).not.toBeNull()
})

test('the line goes round a box in the gap; side by side it goes across; frames that meet otherwise get none', () => {
  const a = { x: 0, y: 0, width: 500, height: 200 }
  const b = { x: 0, y: 260, width: 500, height: 200 }
  const free = requestLine(a, b, [])!
  expect(free).toEqual({ x1: 350, y1: 200, x2: 350, y2: 260 })
  // A box where the line would go: the nearest place past it.
  const inTheWay = { x: 300, y: 210, width: 100, height: 40 }
  const moved = requestLine(a, b, [inTheWay])!
  expect(moved.x1 <= 300 || moved.x1 >= 400).toBe(true)
  expect(moved.y1).toBe(200)
  // Side by side: straight across the gap, at a height both share.
  const right = { x: 570, y: 40, width: 400, height: 300 }
  expect(requestLine(a, right, [])).toEqual({ x1: 500, y1: 152, x2: 570, y2: 152 })
  // Overlapping frames, a corner apart, or a box across the whole gap: no line.
  expect(requestLine(a, { ...b, y: 100 }, [])).toBeNull()
  expect(requestLine(a, { x: 600, y: 300, width: 100, height: 100 }, [])).toBeNull()
  expect(requestLine(a, b, [{ x: -10, y: 210, width: 520, height: 40 }])).toBeNull()
})

test('who asked whom waits for whom; once answered the same line says so, solid', () => {
  const g = deriveGraph(asked(), TEAMS)
  expect((g.nodes.find(n => n.id === 'agent:wc')!.data as AgentData).activity).toBe('Waiting for Backend / API')
  const done = deriveGraph(asked('answered'), TEAMS).edges.filter(e => e.request)
  expect(done.map(e => e.request?.label)).toEqual(['answered ✓'])
  expect(deriveGraph(asked('declined'), TEAMS).edges.find(e => e.request)?.request?.label).toBe('request declined by Backend / API')
})

test('asked twice one way, declined twice: one line, one label with its count, each request in full on its title', () => {
  // (Live, 4 Nov: two "declined" labels stacked on one line between the Web app's frame and Docs'.)
  const once = asked('declined')
  const twice = {
    ...once,
    agents: [...once.agents, sub('bl3', 'Backend / API lead', 'r', 'completed', { name: 'Backend / API lead 3', tool_call_id: 's8', report: 'Declined: still a file' })],
    toolCalls: [
      ...once.toolCalls,
      toolCall('9', 'r', 'request_work', 'succeeded', JSON.stringify({ to: 'Backend / API', what: 'GET /api/items again' }), { agent_id: 'wc' }),
      toolCall('s8', 'r', 'spawn_agent', 'succeeded', JSON.stringify({ role: 'Backend / API lead', task: '…', asked_by: 'Web app' }), { parent_call_id: '9' }),
    ],
  }
  const lines = foldGraph(deriveGraph(twice, TEAMS), {}).edges.filter(e => e.request)
  expect(lines.map(e => [e.id, e.request!.label, e.request!.open, e.request!.calls])).toEqual([['ask:5', 'request declined by Backend / API ×2', false, ['5', '9']]])
  expect(lines[0].request!.title.split('\n')).toEqual([
    "Web app's Coder → Backend / API: GET /api/items, 20 a page - Backend / API lead 2 declined: the page reads a file",
    "Web app's Coder → Backend / API: GET /api/items again - Backend / API lead 3 declined: still a file",
  ])
})

test('the chat card says who gave it to whom and who waits, then the answer', () => {
  const line = (state: ReturnType<typeof asked>) => {
    const [request] = requestsOf(state)
    return standsLine(request, state.agents.findLast(a => a.parent_agent_id === request.lead?.id))
  }
  expect(line(asked())).toBe("Backend / API lead 2 gave it to its Coder · at work · Web app's Coder waits")
  expect(line(asked('answered'))).toBe('Backend / API lead 2 answered ✓')
  expect(line(asked('declined'))).toBe('Backend / API lead 2 declined: the page reads a file')
  expect(requestsOf(asked())[0].contract).toBe(true)
})

// K-shared-bagli (mockup Z3; cards, batch-26): a card for each team at its frame's top-right; everyone's beside the Lead.

/** The two teams' turn, as they used the shared folder, the notebook and the memory. */
function used(files = ['web-app/spec.md']) {
  const state = asked('answered')
  const written = (id: string, by: string, path: string) =>
    toolCall(id, 'r', 'write_shared', 'succeeded', JSON.stringify({ path }), { agent_id: by, result: `written: .koloni/shared/${path} - every team reads it with read_shared` })
  return {
    ...state,
    agents: state.agents.map(a =>
      a.id === 'r' ? { ...a, facts_given: ['f1', 'f2'] } : a.id === 'bl2' ? { ...a, task: 'Their contract is in the shared folder: contracts/get-api-items-20-a-page.md (read it with read_shared).' } : a,
    ),
    toolCalls: [...state.toolCalls, ...files.map((path, at) => written(`w${at}`, 'wc', path)), written('wb', 'bc', 'backend-api/items-endpoint.md'), toolCall('m1', 'r', 'recall', 'succeeded', '{}', { agent_id: 'bc' })],
    boardPosts: [note('n1', 'r', { agent_id: 'r', content: 'Web app waits on the API.' }), note('n2', 'r', { agent_id: 'wc', content: 'Pages are 20, by name.' })],
  }
}
const rows = (g: ReturnType<typeof deriveGraph>, id: string) => (g.nodes.find(n => n.id === id)?.data as SharedData).rows.map(row => `${row.kind}: ${row.text}`)

test('each team’s card holds what it wrote to the shared folder and the notebook, and the memory it used; everyone’s beside the Lead', () => {
  const g = deriveGraph(used(), TEAMS)
  expect(g.nodes.filter(n => n.kind === 'shared').map(n => n.id)).toEqual(['shared:r:top', 'shared:r:team:r:web', 'shared:r:team:r:api', 'shared:r:ask:5'])
  expect(rows(g, 'shared:r:top')).toEqual(['notebook: Lead: “Web app waits on the API.”', 'memory: 2 facts given'])
  expect(rows(g, 'shared:r:team:r:web')).toEqual(['file: web-app/spec.md', 'notebook: Coder: “Pages are 20, by name.”'])
  expect(rows(g, 'shared:r:team:r:api')).toEqual(['file: backend-api/items-endpoint.md', 'memory: 1 lookup'])
  // The request's contract: a block of its own, on an arm from the request's line.
  expect(rows(g, 'shared:r:ask:5')).toEqual(['file: contracts/get-api-items-20-a-page.md'])
  expect(g.edges.filter(e => e.shared).map(e => [e.source, e.target, e.shared])).toEqual([
    ['agent:r', 'shared:r:top', { colour: 'var(--accent)', dotted: false }],
    ['team:r:web', 'shared:r:team:r:web', { colour: expect.any(String), dotted: false }],
    ['team:r:api', 'shared:r:team:r:api', { colour: expect.any(String), dotted: false }],
    ['team:r:web', 'shared:r:ask:5', { colour: 'var(--request)', arm: 'ask:5' }],
  ])
  // At most two of a kind, then how many more.
  expect(rows(deriveGraph(used(['a/1.md', 'a/2.md', 'a/3.md']), TEAMS), 'shared:r:team:r:web').slice(0, 3)).toEqual(['file: a/1.md', 'file: a/2.md', 'more: +1 more file'])
  // A turn that used none of them: no card.
  expect(deriveGraph(asked('answered'), TEAMS).nodes.some(n => n.kind === 'shared')).toBe(false)
  // ...but where the shared folder has files - of any turn -, a way to all of them, at the foot of everyone's card - or,
  // with nothing else, that alone - everyone's still.
  const before = [{ path: 'decisions/old.md', at: '2026-10-01T10:00:00Z' }, { path: 'web-app/old.md', at: '2026-10-01T10:00:00Z' }]
  expect(rows(deriveGraph(asked('answered'), TEAMS, before), 'shared:r:top')).toEqual(['folder: All shared files (2) →'])
  expect((deriveGraph(asked('answered'), TEAMS, before).nodes.find(n => n.id === 'shared:r:top')!.data as SharedData).who).toBe('Everyone')
  expect(rows(deriveGraph(used(), TEAMS, before), 'shared:r:top').at(-1)).toBe('folder: All shared files (2) →')
})

test('each card stands at its team frame’s top-right, its line very short, straight and level with the frame’s header; no card lies on a box or a card, no line crosses one', () => {
  const g = foldGraph(deriveGraph(used(), TEAMS), {})
  const { positions, sizes, lines } = layoutGraph(g.nodes, g.edges)
  const at = (id: string) => box(positions, sizes, id)
  const cards = g.nodes.filter(n => n.kind === 'shared')
  const boxes = g.nodes.filter(n => !n.parent && n.kind !== 'shared')
  const others = (...ids: string[]) => [...boxes, ...cards].filter(n => !ids.includes(n.id)).map(n => at(n.id))
  for (const [frame, card] of [['team:r:web', 'shared:r:team:r:web'], ['team:r:api', 'shared:r:team:r:api']]) {
    const [f, c, line] = [at(frame), at(card), lines[`shared:${card}`]]
    // Its top level with the frame's; from the frame's right edge straight to it, in the frame's header, into its name.
    expect(c.y).toBe(f.y)
    expect(c.x - (f.x + f.width)).toBe(CARD_GAP)
    expect([line.x1, line.x2, line.y1]).toEqual([f.x + f.width, c.x, line.y2])
    expect(line.y1).toBeGreaterThan(f.y)
    expect(line.y1).toBeLessThan(f.y + TEAM_HEAD)
    expect(line.y1).toBe(c.y + blockSize(g.nodes.find(n => n.id === card)!.data as SharedData).door)
    expect(crosses(line, others(frame, card))).toBe(false)
  }
  // The contract's arm: from the request's line, in the gap between the frames, to its card - right of both frames,
  // and past the lower team's card it would lie on.
  const [arm, contract] = [lines['shared:shared:r:ask:5'], at('shared:r:ask:5')]
  const [web, api] = [at('team:r:web'), at('team:r:api')]
  expect(arm.y1).toBeGreaterThan(Math.min(web.y + web.height, api.y + api.height))
  expect(arm.y1).toBeLessThan(Math.max(web.y, api.y))
  expect(arm.x2).toBe(contract.x)
  expect(contract.x).toBeGreaterThan(at('shared:r:team:r:api').x)
  expect(crosses(arm, others('shared:r:ask:5'))).toBe(false)
  // Everyone's beside the Lead, level with it, on a short straight line from it (the user, 28 Oct); what hangs off the Lead starts under it.
  const [lead, everyone] = [at('agent:r'), at('shared:r:top')]
  expect([everyone.x, everyone.y]).toEqual([lead.x + lead.width + COL_GAP, lead.y])
  expect(web.y).toBeGreaterThan(everyone.y + everyone.height)
  const joined = lines['shared:shared:r:top']
  expect([joined.x1, joined.x2, joined.y1]).toEqual([lead.x + lead.width, everyone.x, joined.y2])
  expect(joined.y1).toBe(everyone.y + blockSize(g.nodes.find(n => n.id === 'shared:r:top')!.data as SharedData).door)
  expect(crosses(joined, others('agent:r', 'shared:r:top'))).toBe(false)
  // Only as tall as what it holds; and none on a box or another card.
  expect(everyone.height).toBe(blockSize(g.nodes.find(n => n.id === 'shared:r:top')!.data as SharedData).height)
  const overlap = (a: ReturnType<typeof at>, b: ReturnType<typeof at>) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
  for (const card of cards) for (const other of others(card.id)) expect(overlap(at(card.id), other), card.id).toBe(false)
})

test('a block’s rows: a file read in the Workspace or taken in, a note in full on hover, the memory page; its name lights its team; no fold, no close', async () => {
  const light = vi.fn()
  const openMemory = vi.fn()
  const g = deriveGraph(used(), TEAMS)
  const draw = (id: string) =>
    render(
      <ReactFlowProvider>
        <NodeActions.Provider value={{ light, openMemory }}>
          <SharedNode {...({ id, data: g.nodes.find(n => n.id === id)!.data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
        </NodeActions.Provider>
      </ReactFlowProvider>,
    )
  draw('shared:r:team:r:web')
  const block = screen.getByRole('region', { name: 'Web app: shared, noted, remembered' })
  expect(within(block).getByRole('button', { name: 'web-app/spec.md' })).toBeInTheDocument()
  expect(within(block).getByRole('button', { name: 'Take web-app/spec.md into the project' })).toBeInTheDocument()
  expect(within(block).getByRole('button', { name: /Pages are 20, by name\.” - open it on the Notes tab$/ })).toHaveAttribute('title', expect.stringMatching(/^Web app · Coder · .* · to the notebook\nPages are 20, by name\.$/))
  await userEvent.click(within(block).getByRole('button', { name: 'Show Web app’s line' }))
  expect(light).toHaveBeenCalledWith('shared:r:team:r:web')
  expect(within(block).queryByRole('button', { name: /fold|close/i })).not.toBeInTheDocument()
  cleanup()
  draw('shared:r:team:r:api')
  await userEvent.click(screen.getByRole('button', { name: 'Memory: 1 lookup - open the Memory page' }))
  expect(openMemory).toHaveBeenCalledOnce()
  cleanup()
  // All shared files: the Workspace window, open at the folder.
  const all = deriveGraph(used(), TEAMS, [{ path: 'decisions/old.md', at: '2026-10-01T10:00:00Z' }])
  render(
    <ReactFlowProvider>
      <SharedNode {...({ id: 'shared:r:top', data: all.nodes.find(n => n.id === 'shared:r:top')!.data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
    </ReactFlowProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'All shared files (1) →' }))
  expect(useApp.getState().filesAt.key).toBe('folder:.koloni/shared')
  cleanup()
  // With nothing else, the slim card of all the shared files alone.
  const slim = deriveGraph(asked('answered'), TEAMS, [{ path: 'decisions/old.md', at: '2026-10-01T10:00:00Z' }])
  render(
    <ReactFlowProvider>
      <SharedNode {...({ id: 'shared:r:top', data: slim.nodes.find(n => n.id === 'shared:r:top')!.data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
    </ReactFlowProvider>,
  )
  expect(screen.getByRole('region', { name: 'Everyone: shared, noted, remembered' })).toHaveTextContent('All shared files (1) →')
  cleanup()
})

test('two requests on one line, each with its contract: one card for both, its arm reaching it', () => {
  // (Live, 4 Nov: "answered ✓ · request declined by Docs" - two cards of one id, the arm ending short of the one drawn.)
  const state = used()
  const two = {
    ...state,
    agents: [
      ...state.agents,
      sub('bl3', 'Backend / API lead', 'r', 'completed', { name: 'Backend / API lead 3', tool_call_id: 's8', report: 'Declined: no', task: 'Their contract is in the shared folder: contracts/items-again.md.' }),
    ],
    toolCalls: [
      ...state.toolCalls,
      toolCall('9', 'r', 'request_work', 'succeeded', JSON.stringify({ to: 'Backend / API', what: 'GET /api/items again', contract: 'x' }), { agent_id: 'wc' }),
      toolCall('s8', 'r', 'spawn_agent', 'succeeded', JSON.stringify({ role: 'Backend / API lead', task: '…', asked_by: 'Web app' }), { parent_call_id: '9' }),
    ],
  }
  const g = foldGraph(deriveGraph(two, TEAMS), {})
  expect(new Set(g.nodes.map(n => n.id)).size).toBe(g.nodes.length)
  expect(g.nodes.filter(n => n.id.startsWith('shared:r:ask:')).map(n => n.id)).toEqual(['shared:r:ask:5'])
  expect(rows(g, 'shared:r:ask:5')).toEqual(['file: contracts/get-api-items-20-a-page.md', 'file: contracts/items-again.md'])
  const { positions, lines } = layoutGraph(g.nodes, g.edges)
  expect(lines['shared:shared:r:ask:5'].x2).toBe(positions['shared:r:ask:5'].x)
})
