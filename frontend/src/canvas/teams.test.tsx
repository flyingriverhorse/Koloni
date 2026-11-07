import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import type { Away, ChatTeamState, Merge, Room } from '../api/types'
import { agent, command, conversation, convState, fileChange, note, question, run, toolCall } from '../test-fixtures'
import { waitingCards } from '../chat/chatLine'
import { type ReadyData, type TeamData, deriveGraph } from './deriveGraph'
import { copyLine } from '../changes/copies'
import { chatColours, talkColours, teamColour, teamColours } from '../agents/teamRun'
import { applyEvent } from '../state/applyEvent'
import { foldAll, foldGraph } from './foldGraph'
import { NODE_H, DOOR_PAD, TEAM_HEAD, TEAM_OUT, blockSize, crosses, layoutGraph } from './layout'
import { ReadyNode, TeamNode } from './nodes'
import type { SharedData } from './sharedColumn'
import { SharedNode } from './SharedNode'

import { NodeActions, ToggleGroup } from './toggleGroup'

// Slice 84b-2: a chat team's recipe on the canvas - its frame, its step strip, fold, and "Ready for you".

const steps = (now: string): ChatTeamState['steps'] =>
  ['Write the spec', 'Build it', 'Reviews', 'You'].map((name, at, all) => {
    const index = all.indexOf(now)
    return { id: String(at), name, state: at < index ? 'done' : at === index ? 'now' : 'next', round: name === 'Build it' ? 1 : 0, room: false, own_check: false, left_out: [], group: false }
  })
const row = (status: ChatTeamState['status'], now: string, agents = ['spec', 'coder']) => ({
  team_id: 'web',
  recipe_id: null,
  no_recipe: false,
  picked_by: 'user' as const,
  why: null,
  state: { run_id: 'r', team: 'Web app', recipe: 'Feature', status, why: null, steps: steps(now), agents, ended_ready: false, passes: [] },
})
const team = (status: ChatTeamState['status'], now: string, more: Parameters<typeof convState>[0] = {}) =>
  convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [row(status, now)] },
    runs: [run('r')],
    agents: [
      agent('r'),
      agent('r', 'completed', { id: 'spec', role_name: 'Spec writer', depth: 1, parent_agent_id: 'r', input_tokens: 9000, output_tokens: 1000 }),
      agent('r', status === 'running' ? 'running' : 'completed', {
        id: 'coder',
        role_name: 'Coder',
        depth: 1,
        parent_agent_id: 'r',
        input_tokens: 20000,
        output_tokens: 2000,
        findings: [],
      }),
    ],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', path: 'a.py' }), fileChange('f2', 'r', { agent_id: 'coder', path: 'a.py' })],
    ...more,
  })

test('K-shared-bagli, batch-26: Ready for you stands right of the turn at its top, past the frame’s card; the frame’s line to it leaves low, under the card - folded too', () => {
  const written = toolCall('w', 'r', 'write_shared', 'succeeded', '{}', { agent_id: 'coder', result: 'written: .koloni/shared/web-app/spec.md - every team reads it' })
  const g = deriveGraph(team('ready', 'You', { toolCalls: [written] }))
  for (const folds of [{}, { 'team:r:web': false }]) {
    const drawn = foldGraph(g, folds)
    const { positions, sizes } = layoutGraph(drawn.nodes, drawn.edges)
    const [card, ready, frame] = ['shared:r:team:r:web', 'ready:r', 'team:r:web'].map(id => ({ ...positions[id], ...(sizes[id] ?? { width: 220, height: 104 }) }))
    expect(ready.y).toBe(0)
    // (The lane's bus is just left of Ready: past the card.)
    expect(ready.x - DOOR_PAD / 2).toBeGreaterThan(card.x + card.width)
    // The line leaves the frame TEAM_OUT over its foot (canvas.css .team-out): under the card.
    expect(card.y + card.height).toBeLessThan(frame.y + frame.height - TEAM_OUT)
  }
})

test('K-shared-bagli, three teams: each one’s line to its card crosses no box - Ready for you, another frame, another card', () => {
  // (The review, N1.)
  const three = ['web', 'api', 'docs'].map((id, at) => ({
    ...row('ready', 'You', [`a${at}`, `b${at}`]),
    team_id: id,
    state: { ...row('ready', 'You').state, team: ['Web app', 'Backend', 'Docs'][at], agents: [`a${at}`, `b${at}`] },
  }))
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: three },
    runs: [run('r')],
    agents: [agent('r'), ...[0, 1, 2].flatMap(at => [agent('r', 'completed', { id: `a${at}`, role_name: 'Spec writer', depth: 1, parent_agent_id: 'r' }), agent('r', 'completed', { id: `b${at}`, role_name: 'Coder', depth: 1, parent_agent_id: 'r' })])],
    toolCalls: [0, 1, 2].map(at => toolCall(`w${at}`, 'r', 'write_shared', 'succeeded', '{}', { agent_id: `b${at}`, result: `written: .koloni/shared/t${at}/a.md - every team reads it` })),
  })
  const g = deriveGraph(state)
  const { positions, sizes, lines } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: 220, height: 104 }) })
  const shared = g.edges.filter(e => e.shared)
  expect(shared).toHaveLength(3)
  for (const e of shared) {
    const line = lines[e.id]
    expect(line).toBeDefined()
    const others = g.nodes.filter(n => !n.parent && positions[n.id] && n.id !== e.source && n.id !== e.target).map(n => box(n.id))
    expect(crosses(line, others), e.id).toBe(false)
  }
})

test('batch-26 review, S2: three folded frames, with cards of 7 rows and 3 - each frame as tall as its card and the line to Ready under it, each card at its frame with its line, none on another', () => {
  const three = ['web', 'api', 'docs'].map((id, at) => ({
    ...row('ready', 'You', [`a${at}`, `b${at}`]),
    team_id: id,
    state: { ...row('ready', 'You').state, team: ['Web app', 'Backend', 'Docs'][at], agents: [`a${at}`, `b${at}`] },
  }))
  const wrote = (id: string, by: string, path: string) => toolCall(id, 'r', 'write_shared', 'succeeded', '{}', { agent_id: by, result: `written: .koloni/shared/${path} - every team reads it` })
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: three },
    runs: [run('r')],
    agents: [agent('r'), ...[0, 1, 2].flatMap(at => [agent('r', 'completed', { id: `a${at}`, role_name: 'Spec writer', depth: 1, parent_agent_id: 'r' }), agent('r', 'completed', { id: `b${at}`, role_name: 'Coder', depth: 1, parent_agent_id: 'r' })])],
    // Web app: three files and three notes (two of each, then "+1 more") and a lookup - 7 rows; Backend: a file, a
    // note and a lookup - 3; Docs: a file.
    toolCalls: [
      ...[1, 2, 3].map(n => wrote(`w${n}`, 'b0', `web/${n}.md`)),
      wrote('w4', 'b1', 'api/1.md'),
      wrote('w5', 'b2', 'docs/1.md'),
      toolCall('m0', 'r', 'recall', 'succeeded', '{}', { agent_id: 'a0' }),
      toolCall('m1', 'r', 'recall', 'succeeded', '{}', { agent_id: 'a1' }),
    ],
    boardPosts: [...[1, 2, 3].map(n => note(`n${n}`, 'r', { agent_id: 'a0', content: `web note ${n}` })), note('n4', 'r', { agent_id: 'a1', content: 'api note' })],
  })
  const g = foldGraph(deriveGraph(state), { 'team:r:web': false, 'team:r:api': false, 'team:r:docs': false })
  const { positions, sizes, lines } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: 220, height: 104 }) })
  const rowsOf = (id: string) => (g.nodes.find(n => n.id === id)!.data as { rows: unknown[] }).rows.length
  expect(['web', 'api', 'docs'].map(id => rowsOf(`shared:r:team:r:${id}`))).toEqual([7, 3, 1])
  const placed = g.nodes.filter(n => !n.parent && positions[n.id])
  for (const id of ['web', 'api', 'docs']) {
    const [frame, card] = [box(`team:r:${id}`), box(`shared:r:team:r:${id}`)]
    expect(card.y).toBe(frame.y)
    expect(lines[`shared:shared:r:team:r:${id}`], id).toBeDefined()
    expect(card.y + card.height).toBeLessThan(frame.y + frame.height - TEAM_OUT)
    for (const other of placed.filter(n => n.id !== `shared:r:team:r:${id}`).map(n => box(n.id)))
      expect(card.x < other.x + other.width && other.x < card.x + card.width && card.y < other.y + other.height && other.y < card.y + card.height, id).toBe(false)
  }
})

test('the user’s (6 Nov): a card says what it left out - “+1 more file”, “+2 more notes” - and a click on either unfolds it in place, “Fewer” folds it again', async () => {
  const wrote = (n: number) => toolCall(`w${n}`, 'r', 'write_shared', 'succeeded', '{}', { agent_id: 'coder', result: `written: .koloni/shared/web/${n}.md - every team reads it` })
  const g = deriveGraph(team('running', 'Build it', { toolCalls: [1, 2, 3].map(wrote), boardPosts: [1, 2, 3, 4].map(n => note(`n${n}`, 'r', { agent_id: 'coder', content: `web note ${n}` })) }))
  const id = 'shared:r:team:r:web'
  const card = (folds: Record<string, boolean>) => foldGraph(g, folds).nodes.find(n => n.id === id)!.data as SharedData
  const said = (data: SharedData) => data.rows.map(r => (r.kind === 'notebook' ? r.text.replace(/^.*“(.*)”$/, '$1') : r.text))
  // Folded: two of each kind - the files first, the newest notes - and what is left out, by its name.
  expect(said(card({}))).toEqual(['web/1.md', 'web/2.md', '+1 more file', 'web note 3', 'web note 4', '+2 more notes'])
  expect(said(card({ [id]: true }))).toEqual(['web/1.md', 'web/2.md', 'web/3.md', 'web note 1', 'web note 2', 'web note 3', 'web note 4', 'Fewer'])
  // Unfolded, laid out as tall as it is, on no other box.
  const open = foldGraph(g, { [id]: true })
  const { positions, sizes } = layoutGraph(open.nodes, open.edges)
  const box = (one: string) => ({ ...positions[one], ...(sizes[one] ?? { width: 220, height: 104 }) })
  const drawn = { ...positions[id], width: 234, height: blockSize(card({ [id]: true })).height }
  expect(drawn.height).toBeGreaterThan(blockSize(card({})).height)
  for (const other of open.nodes.filter(n => !n.parent && n.id !== id && n.kind !== 'team' && positions[n.id]).map(n => box(n.id)))
    expect(crosses({ x1: drawn.x, y1: drawn.y, x2: drawn.x + drawn.width, y2: drawn.y + drawn.height }, [other])).toBe(false)
  // Each "+N more" a button that unfolds the card; "Fewer" folds it.
  const toggle = vi.fn()
  const draw = (data: SharedData) =>
    render(
      <ReactFlowProvider>
        <ToggleGroup.Provider value={toggle}>
          <SharedNode {...({ id, data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
        </ToggleGroup.Provider>
      </ReactFlowProvider>,
    )
  draw(card({}))
  await userEvent.click(screen.getByRole('button', { name: '+2 more notes' }))
  await userEvent.click(screen.getByRole('button', { name: '+1 more file' }))
  cleanup()
  draw(card({ [id]: true }))
  await userEvent.click(screen.getByRole('button', { name: 'Fewer' }))
  expect(toggle.mock.calls).toEqual([[id], [id], [id]])
  cleanup()
  // With no more than two of a kind, nothing to unfold.
  const two = deriveGraph(team('running', 'Build it', { toolCalls: [1, 2].map(wrote) })).nodes.find(n => n.id === id)!.data as SharedData
  expect(two.rows.map(r => r.text)).toEqual(['web/1.md', 'web/2.md'])
  expect(two.all).toBeUndefined()
})

test('a team frame stands before its agents, in the team colour, its agents marked as in it', () => {
  const g = deriveGraph(team('running', 'Build it'))
  const ids = g.nodes.map(n => n.id)
  expect(ids.indexOf('team:r:web')).toBeLessThan(ids.indexOf('agent:spec'))
  const frame = g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  expect(frame).toMatchObject({ team: 'Web app', recipe: 'Feature', stands: 'running', tokens: '32k tokens', parentId: 'r', inside: 2 })
  expect(frame.summary).toBe('at Build it · round 2')
  expect(g.nodes.filter(n => n.team === 'team:r:web').map(n => n.id)).toEqual(['agent:spec', 'agent:coder'])
  // The Lead is no agent of the team; and the teams meet in one node, joined by the frame.
  expect(g.nodes.find(n => n.id === 'agent:r')?.team).toBeUndefined()
  expect(g.edges.some(e => e.source === 'team:r:web' && e.target === 'ready:r')).toBe(true)
})

test('a team frame folds only by the user, and folded hides its agents; Fold all folds it too', () => {
  const g = deriveGraph(team('in', 'You'))
  // Done, its agents' own boxes would close by themselves; the frame stays open.
  expect((foldGraph(g, {}).nodes.find(n => n.id === 'team:r:web')!.data as TeamData).open).toBe(true)
  expect(foldAll(g, false)).toHaveProperty(['team:r:web'], false)
  const folded = foldGraph(g, { 'team:r:web': false })
  expect(folded.nodes.map(n => n.id)).not.toContain('agent:coder')
  expect(folded.nodes.map(n => n.id)).toContain('team:r:web')
})

test('the frame is laid out round its agents, its header above them; folded, it stands under the Lead', () => {
  const g = foldGraph(deriveGraph(team('running', 'Build it')), {})
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const [frame, spec, coder] = ['team:r:web', 'agent:spec', 'agent:coder'].map(id => ({ ...positions[id], ...sizes[id] }))
  expect(frame.y).toBe(spec.y - TEAM_HEAD)
  expect(frame.x).toBeLessThan(spec.x)
  expect(frame.y + frame.height).toBeGreaterThan(coder.y + coder.height)
  expect(positions['ready:r'].x).toBeGreaterThan(frame.x + frame.width)
  const shut = foldGraph(deriveGraph(team('running', 'Build it')), { 'team:r:web': false })
  const folded = layoutGraph(shut.nodes, shut.edges)
  expect(folded.positions['team:r:web'].x).toBeGreaterThan(folded.positions['agent:r'].x)
})

test('a room in a recipe’s step (84e) is drawn inside its team’s frame, the frame round it, its step marked Room', () => {
  const room = { id: 'o', run_id: 'r', agent_id: 'r', goal: 'Meet on it', status: 'working', outcome: null, why: null, members: [
    { agent_id: 'spec', role: 'Spec writer', status: 'in' }, { agent_id: 'coder', role: 'Coder', status: 'in' }] } as unknown as Room
  const state = team('running', 'Build it', { rooms: [room] })
  state.conversation.teams[0].state!.steps[1].room = true
  const g = foldGraph(deriveGraph(state), {})
  expect(g.nodes.find(n => n.id === 'room:o')?.team).toBe('team:r:web')
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const [frame, met] = [{ ...positions['team:r:web'], ...sizes['team:r:web'] }, positions['room:o']]
  expect(met.y).toBeGreaterThanOrEqual(frame.y + TEAM_HEAD)
  expect(met.y + NODE_H).toBeLessThanOrEqual(frame.y + frame.height)
  const data = g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  draw(<TeamNode {...props('team:r:web', data)} />)
  expect(within(screen.getByRole('list', { name: 'Feature: its steps' })).getAllByRole('listitem')[1]).toHaveTextContent('Build itRoom · round 2')
})

const draw = (
  node: React.ReactNode,
  on = { expand: vi.fn(), raw: vi.fn(), openList: vi.fn(), stopTeam: vi.fn().mockResolvedValue(undefined), openChange: vi.fn() },
  toggle = vi.fn(),
) => {
  render(
    <ReactFlowProvider>
      <ToggleGroup.Provider value={toggle}>
        <NodeActions.Provider value={on}>{node}</NodeActions.Provider>
      </ToggleGroup.Provider>
    </ReactFlowProvider>,
  )
  return { on, toggle }
}
const props = <T,>(id: string, data: T) => ({ id, data, selected: false }) as unknown as NodeProps<Node<T & Record<string, unknown>>>

test('the step strip ticks the steps done, fills the one now, and Stop and fold are the frame own', async () => {
  const data = deriveGraph(team('running', 'Build it')).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  const { on, toggle } = draw(<TeamNode {...props('team:r:web', data)} />)
  const strip = screen.getByRole('list', { name: 'Feature: its steps' })
  expect(within(strip).getAllByRole('listitem').map(li => li.textContent)).toEqual(['Write the spec ✓', 'Build it · round 2', 'Reviews', 'You'])
  expect(within(strip).getByText('Build it · round 2')).toHaveAttribute('aria-current', 'step')
  await userEvent.click(screen.getByRole('button', { name: 'Stop Web app' }))
  expect(on.stopTeam).toHaveBeenCalledWith('web')
  await userEvent.click(screen.getByRole('button', { name: 'Fold Web app' }))
  expect(toggle).toHaveBeenCalledWith('team:r:web')
})

test('K-evrim: a step of candidates says how many ran, the best score its measure gave, and a target its rounds missed', () => {
  const state = team('running', 'Reviews')
  const row = state.conversation.teams[0].state!
  row.steps[1].draws = { Coder: 3 }
  row.steps[1].best = 85
  row.steps[1].missed = 90
  state.agents.push(
    agent('r', 'completed', { id: 'coder2', role_name: 'Coder', depth: 1, parent_agent_id: 'r' }),
    agent('r', 'completed', { id: 'coder3', role_name: 'Coder', depth: 1, parent_agent_id: 'r' }),
  )
  row.passes = [{ part: '1', agents: ['coder', 'coder2', 'coder3'] }]
  draw(<TeamNode {...props('team:r:web', deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData)} />)
  const strip = screen.getByRole('list', { name: 'Feature: its steps' })
  expect(within(strip).getAllByRole('listitem')[1]).toHaveTextContent('Build it · Coder ×3 · best 85 · target 90 not reached ✓')
})

test('K-tarif-kol: a group at work shows its branches in the strip - each step done, now, next or stopped', () => {
  const state = team('running', 'Reviews')
  const row = state.conversation.teams[0].state!
  row.steps[2].group = true
  row.steps[2].branches = [
    [
      { name: 'Tests', state: 'done' },
      { name: 'Fix', state: 'now' },
    ],
    [{ name: 'Review', state: 'next' }],
    [{ name: 'Docs', state: 'stopped' }],
  ]
  draw(<TeamNode {...props('team:r:web', deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData)} />)
  const items = within(screen.getByRole('list', { name: 'Feature: its steps' })).getAllByRole('listitem')
  expect(items[2]).toHaveTextContent('Reviews: Tests ✓ → Fix … · Review · Docs (stopped)')
  // (A step that is no group, as before.)
  expect(items[1].textContent).toBe('Build it ✓ · round 2')
})

test('K-rol-cogul: a step drawn "at most 3" that opened two of its role says so in the strip, by its last pass there', () => {
  const state = team('running', 'Reviews')
  const row = state.conversation.teams[0].state!
  row.steps[1].draws = { Coder: 3 }
  state.agents.push(
    agent('r', 'completed', { id: 'coder2', role_name: 'Coder', depth: 1, parent_agent_id: 'r' }),
    agent('r', 'failed', { id: 'coder3', role_name: 'Coder', depth: 1, parent_agent_id: 'r' }),
  )
  row.passes = [
    { part: '1', agents: ['coder'] },
    { part: '0', agents: ['spec'] },
    { part: '1', agents: ['coder', 'coder2', 'coder3'] },
  ]
  const many = () => (deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData).many?.['1']
  draw(<TeamNode {...props('team:r:web', deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData)} />)
  const strip = screen.getByRole('list', { name: 'Feature: its steps' })
  // (The one that failed is no part of it.)
  expect(within(strip).getAllByRole('listitem').map(li => li.textContent)).toEqual(['Write the spec ✓', 'Build it · Coder ×2 ✓ · round 2', 'Reviews', 'You'])
  // One the user declined never ran.
  state.agents.find(one => one.id === 'coder2')!.status = 'rejected'
  expect(many()).toEqual([])
  // A step of one (two in a group of one-Coder steps, a Try again) says no count.
  state.agents.find(one => one.id === 'coder2')!.status = 'completed'
  row.steps[1].draws = null
  expect(many()).toEqual([])
})

test('batch-17: a recipe at work can be finished now, its buttons waiting for the answer; a review its writer checks and a wait for a reset say so', async () => {
  const state = team('running', 'Build it')
  state.conversation.teams[0].state!.steps[2].own_check = true
  state.conversation.teams[0].state!.why = 'waits till 15:00 for Coder’s limit'
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  const finishTeam = vi.fn().mockReturnValue(new Promise(() => {}))
  draw(<TeamNode {...props('team:r:web', data)} />, { expand: vi.fn(), raw: vi.fn(), finishTeam } as never)
  expect(screen.getByText('Reviews · checked by its own writer')).toBeInTheDocument()
  expect(screen.getByText('at Build it · round 2 · waits till 15:00 for Coder’s limit')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Finish Web app now' }))
  expect(finishTeam).toHaveBeenCalledWith('web')
  expect(screen.getByRole('button', { name: 'Finish Web app now' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Stop Web app' })).toBeDisabled()
})

test('a finished team says what it did, and has no Stop', () => {
  const state = team('in', 'You')
  state.conversation.teams[0].state.steps[2].round = 1 // (R116: the review that sent the work back ran again - the same one round)
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  draw(<TeamNode {...props('team:r:web', data)} />)
  expect(screen.getByText('done · 1 file · 1 round back · 32k tokens')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Stop Web app' })).toBeNull()
})

test('B-126: a team whose agents ran commands says what those changed is counted at Take in', () => {
  const ran = { commands: [command('k1', 'r', { agent_id: 'coder' })] }
  const line = (status: ChatTeamState['status']) => (deriveGraph(team(status, 'You', ran)).nodes.find(n => n.id === 'team:r:web')!.data as TeamData).summary
  expect(line('ready')).toBe("done · 1 file · commands' changes, if any, counted at Take in · 1 round back · 32k tokens")
  expect(line('in')).toBe('done · 1 file · 1 round back · 32k tokens')
})

const ready = (state: ReturnType<typeof team>) => deriveGraph(state).nodes.find(n => n.id === 'ready:r')!.data as ReadyData

test('Ready for you waits, dashed, saying for whom; ready, it needs you, with the checks reported only', async () => {
  draw(<ReadyNode {...props('ready:r', ready(team('running', 'Build it')))} />)
  expect(screen.getByText('WAITS')).toBeInTheDocument()
  expect(screen.getByText('Waits for Web app: Build it.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Take in' })).toBeNull()
})

test('B-192: a suggestion is no finding left - the check passes, saying how many', () => {
  const state = team('ready', 'You')
  const coder = state.agents.find(a => a.id === 'coder')!
  const said = (what: string, blocking: boolean) => ({ what, kind: 'code' as const, role: 'Coder', blocking })
  coder.findings = [said('rename x', false), said('add a docstring', false)]
  expect(ready(state).checks).toEqual([{ text: 'Coder: 2 suggestions', passed: true }])
  coder.findings = [said('greet says Helo', true), said('rename x', false)]
  expect(ready(state).checks).toEqual([{ text: 'Coder: 1 finding left, 1 suggestion', passed: false }])
})

test('ready, it needs you: its checks are what agents reported; what waits is counted and said as the chat’s list has it, answered there', async () => {
  const asked = question('q', 'r', { question: 'Ready for you: Web app (Feature): ready. Take the work into the project?', leave: true, options: ['Take in', 'Ask for changes'] })
  const state = team('ready', 'You', { questions: [asked, question('w', 'r', { agent_id: 'coder' })], commands: [command('k', 'r', { status: 'proposed' })] })
  const data = ready(state)
  // The Coder said "Findings: none"; the Spec writer said nothing of findings: no check is made up for it.
  expect(data.checks).toEqual([{ text: 'Coder: no findings', passed: true }])
  // K-bekleyenler: one count, the chat's - the list is one, and the node only points to it.
  expect(data.waiting).toEqual({ count: waitingCards(state), summary: '1 question · 1 command · 1 copy to take in', mine: 0, decided: 0 })
  const { on } = draw(<ReadyNode {...props('ready:r', data)} />)
  expect(screen.getByText('NEEDS YOU')).toBeInTheDocument()
  expect(screen.getByText('Every team is at its end. Nothing is in the project yet.')).toBeInTheDocument()
  expect(screen.getByText('3')).toBeInTheDocument()
  expect(screen.getByText('1 question · 1 command · 1 copy to take in')).toBeInTheDocument()
  for (const word of ['Take in', 'Ask for changes', 'See the changes', 'Discard']) expect(screen.queryByRole('button', { name: word })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Open the list →' }))
  expect(on.openList).toHaveBeenCalled()
})

test('B-142: a Take in that met a clash needs you - its card waits in the list', () => {
  const clash = { id: 'm', run_id: 'r', agent_id: 'r', status: 'pending', files: [], kept_in: null } as unknown as Merge
  draw(<ReadyNode {...props('ready:r', ready(team('ready', 'You', { merges: [clash] })))} />)
  expect(screen.getByText('NEEDS YOU')).toBeInTheDocument()
  expect(screen.getByText('1 Take in to finish')).toBeInTheDocument()
  expect(screen.queryByText('Nothing waits to be taken in.')).toBeNull()
})

test('B-142 review: what else of the chat waits - a night’s card, another turn’s clash - is counted, but needs no Take in here', () => {
  const card = { id: 'a1', run_id: 'r', status: 'planned', jobs: [] } as unknown as Away
  const theirs = { id: 'm', run_id: 'other', agent_id: 'r', status: 'pending', files: [], kept_in: null } as unknown as Merge
  const data = ready(team('in', 'You', { away: [card], merges: [theirs] }))
  expect([data.waiting.count, data.waiting.mine]).toEqual([2, 0])
  draw(<ReadyNode {...props('ready:r', data)} />)
  expect(screen.queryByText('NEEDS YOU')).toBeNull()
})

test('B-67: a turn that ended before Take in keeps the recipe’s copy - said, and counted for the chat’s list', () => {
  const kept = { id: 'm', run_id: 'r', agent_id: 'r', status: 'interrupted', files: [{ path: 'a.py', state: 'refused' }], kept_in: 'C:/copies/r' } as unknown as Merge
  const state = team('stopped', 'Reviews', { merges: [kept] })
  state.conversation.teams[0].state!.why = 'the turn ended at its Reviews step'
  draw(<ReadyNode {...props('ready:r', ready(state))} />)
  expect(screen.getByText('NEEDS YOU')).toBeInTheDocument()
  expect(screen.getByText(/the work is kept in the recipe’s copy, not in the project/)).toBeInTheDocument()
  // Taken in or discarded from the chat's list (K-bekleyenler): here, said and pointed to.
  expect(screen.getByText('1 copy to take in')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Take in' })).toBeNull()
  // Decided, nothing waits: the way to the list is gone too.
  cleanup()
  draw(<ReadyNode {...props('ready:r', ready(team('stopped', 'Reviews', { merges: [{ ...kept, status: 'rejected' }] })))} />)
  expect(screen.queryByRole('button', { name: 'Open the list →' })).toBeNull()
})

test('after Take in: In the project', () => {
  draw(<ReadyNode {...props('ready:r', ready(team('in', 'You')))} />)
  expect(screen.getByText('In the project ✓')).toBeInTheDocument()
  expect(screen.getByText('IN')).toBeInTheDocument()
})

test('a Take in that left files out is not said to be in the project', () => {
  const state = team('in', 'You')
  state.conversation.teams[0].state = { ...state.conversation.teams[0].state!, status: 'stopped', why: 'not applied: a.py clashes' }
  draw(<ReadyNode {...props('ready:r', ready(state))} />)
  expect(screen.queryByText('In the project ✓')).toBeNull()
  expect(screen.getByText('Not all of it is in the project: not applied: a.py clashes')).toBeInTheDocument()
})

test('B-84: a picked team not started is waited for and named; what is in the project is said team by team', () => {
  const docs = { ...row('waiting', 'none', []), team_id: 'docs', state: { ...row('waiting', 'none', []).state, team: 'Docs', recipe: 'Just write' } }
  const state = team('ready', 'You')
  state.conversation.teams.push(docs)
  // The turn still runs: the card waits for Docs, which has no frame of its own.
  draw(<ReadyNode {...props('ready:r', ready(state))} />)
  expect(screen.getByText('Waits for Docs: not started yet.')).toBeInTheDocument()
  expect(screen.getByText('not started yet')).toBeInTheDocument()
  expect(deriveGraph(state).nodes.some(n => n.id === 'team:r:docs')).toBe(false)
  cleanup()
  // Over, with its work kept: Docs did not start; one team taken in before is not "nothing".
  const over = { ...state, runs: [{ ...state.runs[0], status: 'completed' as const }] }
  over.conversation.teams[0].state = { ...over.conversation.teams[0].state!, status: 'in' }
  const asked = question('q', 'r', { question: 'Ready for you: …', leave: true })
  draw(<ReadyNode {...props('ready:r', ready({ ...over, questions: [asked] }))} />)
  expect(screen.getByText('Docs did not start. In the project: Web app.')).toBeInTheDocument()
  expect(screen.getByText('did not start')).toBeInTheDocument()
})

test('B-84: a team that ended early and whose work went in says it is in, and why it ended', () => {
  const state = team('in', 'You')
  state.conversation.teams[0].state!.why = 'Web app lead ended before its end'
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  expect(data.summary).toBe('done · 1 file · 1 round back · 32k tokens · Web app lead ended before its end')
  expect(ready(state).rows[0].line).toContain('in the project · Web app lead ended before its end')
})

test('B-83: a step its runner ended before is marked skipped on the strip, and Ready for you says so', () => {
  const state = team('stopped', 'Reviews')
  const stopped = state.conversation.teams[0].state!
  stopped.why = 'rule broken: Reviews was not done'
  stopped.steps[2].state = 'skipped'
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  draw(<TeamNode {...props('team:r:web', data)} />)
  const strip = screen.getByRole('list', { name: 'Feature: its steps' })
  expect(within(strip).getAllByRole('listitem')[2]).toHaveTextContent('Reviews · skipped')
  expect(within(strip).getAllByRole('listitem')[2]).toHaveClass('team-step-skipped')
  expect(ready(state).rows[0].line).toBe('stopped: rule broken: Reviews was not done')
})

test('a step that runs only if a problem was found, passed, says so on the strip - no rule broken', () => {
  const state = team('running', 'Reviews')
  Object.assign(state.conversation.teams[0].state!.steps[1], { state: 'skipped', unmet: 'no problem found' })
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  draw(<TeamNode {...props('team:r:web', data)} />)
  const passed = within(screen.getByRole('list', { name: 'Feature: its steps' })).getAllByRole('listitem')[1]
  expect(passed).toHaveTextContent('· skipped: no problem found')
  expect(passed).toHaveClass('team-step-unmet')
  expect(passed).not.toHaveClass('team-step-skipped')
})

test('B-90: a picked team that did not run, alone, is named - with no frame, and laid out', () => {
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [{ team_id: 'p', recipe_id: null, no_recipe: false, picked_by: 'user', why: null, state: { run_id: 'r', team: 'Product', recipe: '', status: 'waiting', why: null, steps: [], agents: [], ended_ready: false, passes: [] } }] },
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
  })
  const g = foldGraph(deriveGraph(state), {})
  expect(g.nodes.some(n => n.kind === 'team')).toBe(false)
  expect(layoutGraph(g.nodes, g.edges).positions['ready:r']).toBeDefined()
  draw(<ReadyNode {...props('ready:r', g.nodes.find(n => n.id === 'ready:r')!.data as ReadyData)} />)
  expect(screen.getByText('Product did not start.')).toBeInTheDocument()
})

test('No teams: no frame and no Ready for you - the canvas as before', () => {
  const g = deriveGraph(convState({ runs: [run('r')], agents: [agent('r')] }))
  expect(g.nodes.some(n => n.kind === 'team' || n.kind === 'ready')).toBe(false)
})

test('a recipe turn says its copy is the recipe’s, not a room’s', () => {
  const state = team('ready', 'You')
  state.agents[0] = { ...state.agents[0], copy: { state: 'own' } } as (typeof state.agents)[0]
  state.agents[2] = { ...state.agents[2], copy: { state: 'parent' } } as (typeof state.agents)[0]
  expect(copyLine(state, state.agents[0])).toBe('holds the recipe’s copy')
  expect(copyLine(state, state.agents[2])).toBe('works in the recipe’s copy')
})

test('two teams at once: each frame round its own lead and agents, one under the other', () => {
  const two = (team_id: string, name: string, agents: string[]) => ({ ...row('running', 'Build it', agents), team_id, state: { ...row('running', 'Build it', agents).state, team: name } })
  const sub = (id: string, role: string, parent: string, depth: number) => agent('r', 'running', { id, role_name: role, parent_agent_id: parent, depth })
  const state = convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: [two('web', 'Web app', ['wl', 'coder']), two('docs', 'Docs', ['dl', 'writer'])] },
    runs: [run('r')],
    agents: [agent('r'), sub('wl', 'Web app lead', 'r', 1), sub('coder', 'Coder', 'wl', 2), sub('dl', 'Docs lead', 'r', 1), sub('writer', 'Docs writer', 'dl', 2)],
  })
  const g = foldGraph(deriveGraph(state), {})
  const { positions, sizes } = layoutGraph(g.nodes, g.edges)
  const box = (id: string) => ({ ...positions[id], ...sizes[id] })
  const inside = (frame: ReturnType<typeof box>, id: string) => {
    const at = positions[id]
    return at.x > frame.x && at.y > frame.y && at.x + sizes[id].width < frame.x + frame.width && at.y + sizes[id].height < frame.y + frame.height
  }
  const [web, docs] = [box('team:r:web'), box('team:r:docs')]
  expect(web.y + web.height).toBeLessThan(docs.y)
  expect(['agent:wl', 'agent:coder'].every(id => inside(web, id))).toBe(true)
  expect(['agent:dl', 'agent:writer'].every(id => inside(docs, id))).toBe(true)
})

test('G1.2: ready with findings left says why on Ready for you, and is not ticked done', () => {
  const state = team('ready', 'Reviews')
  state.conversation.teams[0].state!.why = 'findings are left after 2 rounds of Reviews'
  const row = ready(state).rows[0]
  expect([row.line, row.done]).toEqual(['ready: findings are left after 2 rounds of Reviews', false])
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  expect([data.finished, data.summary]).toEqual([false, 'ready: findings are left after 2 rounds of Reviews'])
})

test('B-84: Ready for you says Take in also takes in what a team that ended early left - not one stopped at its end', () => {
  const asked = question('q', 'r', { question: 'Ready for you: …', leave: true })
  const state = team('stopped', 'Reviews', { questions: [asked], fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', status: 'in_copy' })] })
  state.conversation.teams[0].state!.why = 'Web app lead ended before its end'
  draw(<ReadyNode {...props('ready:r', ready(state))} />)
  expect(screen.getByText('Take in also takes in what Web app left before it stopped.')).toBeInTheDocument()
  cleanup()
  state.conversation.teams[0].state!.ended_ready = true
  expect(ready(state).alsoTakes).toBe('')
})

test('B-101: a team with no recipe beside one has its row, and its own kept copy counted', () => {
  const apart = { id: 'm2', run_id: 'r', agent_id: 'dl', status: 'interrupted', files: [{ path: 'a.py', state: 'refused' }], kept_in: 'C:/copies/dl' } as unknown as Merge
  const asked = question('q', 'r', { question: 'Ready for you: …', leave: true })
  // (The recipe's copy holds a change: its card is a copy to take in too - B-156.)
  const state = team('ready', 'You', { questions: [asked], merges: [apart], fileChanges: [fileChange('fc', 'r', { status: 'in_copy' })] })
  state.conversation.teams.push({ ...row('done', 'none', ['dl', 'writer']), team_id: 'docs', state: { ...row('done', 'none', ['dl', 'writer']).state, team: 'Docs', recipe: '', steps: [] } })
  const data = ready(state)
  expect(data.rows.map(one => [one.team, one.recipe, one.kept])).toEqual([['Web app', 'Feature', null], ['Docs', 'no recipe', 'm2']])
  expect((deriveGraph(state).nodes.find(n => n.id === 'team:r:docs')!.data as TeamData).recipe).toBe('no recipe')
  // Its copy is taken in or discarded from the chat's list: here, counted with the rest.
  draw(<ReadyNode {...props('ready:r', data)} />)
  expect(screen.getByText('2 copies to take in')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: "Take in Docs's copy" })).toBeNull()
})

test('B-110: an agent kept beside the recipe has its row at Ready for you, with Take in or Discard for its copy', () => {
  const apart = { id: 'm3', run_id: 'r', agent_id: 'dbg', status: 'interrupted', files: [{ path: 'a.py', state: 'refused' }], kept_in: 'C:/copies/dbg' } as unknown as Merge
  const state = team('ready', 'You', { merges: [apart] })
  state.agents.push(agent('r', 'completed', { id: 'dbg', name: 'Debugger', role_name: 'Debugger', depth: 1, parent_agent_id: 'r' }))
  const data = ready(state)
  expect(data.rows.map(one => [one.team, one.recipe, one.line, one.kept])).toEqual([
    ['Web app', 'Feature', expect.any(String), null],
    ['Debugger', 'beside the recipe', 'its own kept copy', 'm3'],
  ])
})

test('a team with no recipe at work says so - no "step 0 of 0"', () => {
  const state = team('running', 'Build it')
  state.conversation.teams.push({ ...row('running', 'none', ['dl']), team_id: 'docs', state: { ...row('running', 'none', ['dl']).state, team: 'Docs', recipe: '', steps: [] } })
  const data = ready(state)
  expect(data.rows[1].line).toBe('at work')
  expect(data.waits).toBe('Web app: Build it; Docs: at work')
})

test('a team with no recipe beside one has Stop and no Finish now: it has no recipe to finish', () => {
  const state = team('running', 'Build it')
  state.conversation.teams.push({ ...row('running', 'none', ['dl']), team_id: 'docs', state: { ...row('running', 'none', ['dl']).state, team: 'Docs', recipe: '', steps: [] } })
  const data = deriveGraph(state).nodes.find(n => n.id === 'team:r:docs')!.data as TeamData
  draw(<TeamNode {...props('team:r:docs', data)} />)
  expect(screen.getByRole('button', { name: 'Stop Docs' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Finish Docs now' })).toBeNull()
})

test('a row of before batch-16, whose end is not known, is not said to have ended early', () => {
  const asked = question('q', 'r', { question: 'Ready for you: …', leave: true })
  const state = team('stopped', 'Reviews', { questions: [asked], fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', status: 'in_copy' })] })
  state.conversation.teams[0].state!.ended_ready = null
  expect(ready(state).alsoTakes).toBe('')
})

test('B-107: a finished turn is drawn as it was - the chat’s teams changed after it change neither its frame nor Ready for you', () => {
  const state = team('in', 'You')
  // The page heard the turn's rows as they were; then the user took the team off the chat.
  const later = applyEvent(applyEvent(state, null, 'conversation.updated', state.conversation), null, 'conversation.updated', { ...state.conversation, teams_mode: 'none', teams: [] })
  expect(later.conversation.teams).toEqual([])
  const g = deriveGraph(later)
  expect((g.nodes.find(n => n.id === 'team:r:web')!.data as TeamData).stands).toBe('in')
  expect(ready(later).rows.map(one => one.team)).toEqual(['Web app'])
  expect(g.nodes.find(n => n.id === 'agent:coder')?.team).toBe('team:r:web')
  later.agents[0] = { ...later.agents[0], copy: { state: 'own' } } as (typeof later.agents)[0]
  expect(copyLine(later, later.agents[0])).toBe('holds the recipe’s copy')
  // Loaded afresh, the turn's own record says the same.
  const loaded = { ...later, runs: [{ ...state.runs[0], teams: state.conversation.teams }] }
  expect(deriveGraph(loaded).nodes.some(n => n.id === 'team:r:web')).toBe(true)
})

test('B-103: teams shown together are told apart - their hues far apart - and a team alone keeps its own', () => {
  const ids = ['web', 'backend', 'docs', 'quality', 'design', 'ops']
  const hues = [...teamColours(ids).values()].map(colour => Number(/hsl\((\d+)/.exec(colour)![1]))
  const apart = hues.flatMap((a, i) => hues.slice(i + 1).map(b => Math.min(Math.abs(a - b), 360 - Math.abs(a - b))))
  expect(Math.min(...apart)).toBeGreaterThanOrEqual(40)
  expect(teamColours(['web']).get('web')).toBe(teamColour('web'))
  // In whatever order they are shown - the chat's teams, a turn's - the same colours.
  expect([...teamColours([...ids].reverse())].sort()).toEqual([...teamColours(ids)].sort())
})

test('B-103: an agent kept beside the recipe never takes a team’s colour at Ready for you; a frame is the chat’s colour', () => {
  // ("ml" wants Web app's colour.)
  const apart = { id: 'm3', run_id: 'r', agent_id: 'ml', status: 'interrupted', files: [{ path: 'a.py', state: 'refused' }], kept_in: 'C:/copies/ml' } as unknown as Merge
  const state = team('ready', 'You', { merges: [apart] })
  state.agents.push(agent('r', 'completed', { id: 'ml', name: 'Debugger', role_name: 'Debugger', depth: 1, parent_agent_id: 'r' }))
  const [web, beside] = ready(state).rows
  expect(beside.colour).not.toBe(web.colour)
  expect((deriveGraph(state).nodes.find(n => n.id === 'team:r:web')!.data as TeamData).colour).toBe(chatColours(state).get('web'))
})

test('B-101: a frame drawn from its roles has nothing to stop or finish', () => {
  const data = deriveGraph(team('running', 'Build it')).nodes.find(n => n.id === 'team:r:web')!.data as TeamData
  draw(<TeamNode {...props('team:r:web', { ...data, byRoles: true })} />)
  expect(screen.queryByRole('button', { name: 'Stop Web app' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Finish Web app now' })).toBeNull()
})

test('each pair of agents that talked has a colour of its own, the same on every screen, none a team colour', () => {
  const pairs = ['a|b', 'a|c', 'b|c', 'c|d']
  const colours = talkColours(pairs)
  expect(new Set(colours.values()).size).toBe(pairs.length)
  expect([...talkColours([...pairs].reverse())].sort()).toEqual([...colours].sort())
  const teams = new Set(teamColours(['web', 'docs', 'api']).values())
  for (const colour of colours.values()) expect(teams.has(colour)).toBe(false)
})
