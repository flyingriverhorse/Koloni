import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, onTestFinished, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Provider, Recipe, RecipeGraph, Recipes, Role, RoleModel, Team } from '../api/types'
import { addGroup, addRoom, addStep, changeStep, connect, emptyGraph, layout, loopBack, loopCurve, loopTargets, place, remove, renameGroup, summary, START, targets, tidy, waitFor as waitOn } from './recipeGraph'
import { type RecipeActions, RecipesTab } from './RecipesTab'

beforeEach(() => {
  // React Flow watches its pane and its nodes; jsdom has nothing to watch with.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})
// (Unmounted first: React Flow's late effects still reach for the stubbed ResizeObserver.)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const role = (name: string) => ({ id: name, name }) as Role
const roles = [role('Coder'), role('Reviewer'), role('Spec writer')]
const teams = [{ id: 'web', name: 'Web app', stages: [{ name: 'Design' }, { name: 'Code' }] }] as Team[]
const step = (id: string, name: string, more: Partial<RecipeGraph['steps'][number]> = {}) => ({
  id,
  name,
  who: { role: 'Coder' },
  done_when: 'done' as const,
  if_fails: 'ask' as const,
  ask_me: false,
  group: null,
  ...more,
})
const FEATURE: Recipe = {
  id: 'feature',
  name: 'Feature',
  ready: true,
  project_id: null,
  file: null,
  graph: {
    version: 1,
    steps: [step('build', 'Build it'), step('code', 'Code review', { who: { role: 'Reviewer' }, group: 'g' }), step('ui', 'UI review', { group: 'g' })],
    groups: [{ id: 'g', name: 'All at once, wait for all', wait: 'all' }],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [
      { from: 'start', to: 'build' },
      { from: 'build', to: 'g' },
      { from: 'g', to: 'end' },
    ],
    loops: [{ from: 'g', to: 'build', rounds: 2 }],
  },
}
const list: Recipes = { recipes: [FEATURE], broken: [], writer: { why: null } }

function actions(more: Partial<RecipeActions> = {}): RecipeActions {
  return {
    recipes: vi.fn().mockResolvedValue(list),
    saveRecipe: vi.fn(async (_recipe, body) => ({ id: 'mine', ready: false, project_id: null, file: null, ...body })),
    deleteRecipe: vi.fn().mockResolvedValue(undefined),
    draftRecipe: vi.fn(),
    ...more,
  }
}

const draw = (given = actions(), shown: Recipes = list) => {
  render(<RecipesTab roles={roles} teams={teams} list={shown} projectId={null} actions={given} reload={vi.fn()} />)
  return given
}
const part = (name: RegExp) => screen.getByRole('button', { name })
const panel = () => screen.getByRole('complementary', { name: /^Recipe part / })

// --- the drawing, as the board changes it -----------------------------------------------------------------------------------------

test('a step hangs after the chosen part; a group holds two steps at once; a loop goes back to the step before, two rounds', () => {
  let [graph, first] = addStep(emptyGraph(), START)
  expect(graph.arrows).toEqual([{ from: START, to: first }])
  let group: string
  ;[graph, group] = addGroup(graph, first)
  expect(graph.steps.filter(one => one.group === group)).toHaveLength(2)
  expect(graph.arrows).toContainEqual({ from: first, to: group })
  graph = loopBack(graph, group)
  expect(graph.loops).toEqual([{ from: group, to: first, rounds: 2 }])
  // A step added beside a group's step is in that group too, with no arrow of its own.
  const member = graph.steps.find(one => one.group === group)?.id as string
  const [withThird, third] = addStep(graph, member)
  expect(withThird.steps.find(one => one.id === third)?.group).toBe(group)
  expect(withThird.arrows).toEqual(graph.arrows)
  // The group taken away: its steps, arrows and loop with it.
  const gone = remove(graph, group)
  expect([gone.steps.length, gone.groups.length, gone.loops.length]).toEqual([1, 0, 0])
  expect(gone.arrows).toEqual([{ from: START, to: first }])
})

test('a step put in a group goes on with it: its own arrows go; an arrow is drawn once, never from an end or to the start', () => {
  const [one, a] = addStep(emptyGraph(), START)
  const [two, b] = addStep(one, a)
  const [three, g] = addGroup(two, null)
  const moved = changeStep(three, b, { group: g })
  expect(moved.arrows).toEqual([{ from: START, to: a }])
  expect(connect(moved, START, a)).toBe(moved)
  expect(connect(moved, a, START)).toBe(moved)
})

test('an arrow goes on, never back to a part on the way there; a loop goes back, never inside its own group', () => {
  // Feature: start → build → the group (code, ui) → end.
  expect(targets(FEATURE.graph, 'g')).toEqual([]) // the end it has; back to build would go round with no limit
  expect(targets(FEATURE.graph, 'build')).toEqual(['end']) // not back to the start
  expect(loopTargets(FEATURE.graph, 'g')).toEqual(['build'])
  expect(loopTargets(FEATURE.graph, 'code')).toEqual(['build']) // not its sibling, not its own group
  expect(loopTargets(FEATURE.graph, 'build')).toEqual([]) // nothing comes before it to go back to
})

test('the board lays parts out by rows from the start, a group’s steps inside it; the list says it in one line', () => {
  const places = layout(FEATURE.graph)
  expect(places.start.y).toBeLessThan(places.build.y)
  expect(places.build.y).toBeLessThan(places.g.y)
  expect(places.code).toMatchObject({ x: 12 })
  expect(places.ui.x).toBeGreaterThan(places.code.x) // two branches of one step each: side by side
  expect(summary(FEATURE.graph)).toBe('Build it → 2 at once (≤2 rounds) → Ask me, then in')
})

// B-374: Checks = [Build it → Test it] ∥ [Write docs], the group going on once the first is done.
const CHECKS: Recipe = {
  ...FEATURE,
  id: 'checks',
  name: 'Checks',
  graph: {
    ...FEATURE.graph,
    steps: [step('build', 'Build it', { group: 'g' }), step('test', 'Test it', { group: 'g' }), step('docs', 'Write docs', { group: 'g' })],
    groups: [{ id: 'g', name: 'Checks', wait: 'first' }],
    arrows: [
      { from: 'start', to: 'g' },
      { from: 'build', to: 'test' },
      { from: 'g', to: 'end' },
    ],
    loops: [],
  },
}

test('a group’s branches stand in columns of their own, each one’s steps down it (B-374)', () => {
  const places = layout(CHECKS.graph)
  expect(places.docs.x).not.toBe(places.build.x)
  expect(places.test.x).toBe(places.build.x)
  expect(places.test.y).toBeGreaterThan(places.build.y)
  expect(places.docs.y).toBe(places.build.y)
  // The group holds both columns and both of the first branch's steps.
  expect(places.g.w).toBeGreaterThanOrEqual(places.docs.x + places.docs.w)
  expect(places.g.h).toBeGreaterThan(places.test.y + places.test.h)
})

test('the branches fork from the group and join at its way out; a group that waits for the first says “first done” (B-374)', async () => {
  // React Flow draws an arrow once its parts have a size, and sizes an arrow's words: jsdom gives neither.
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(100)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(50)
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: 0, y: 0, width: 40, height: 10 }) })
  onTestFinished(() => {
    vi.restoreAllMocks()
    delete (SVGElement.prototype as { getBBox?: unknown }).getBBox
  })
  draw(actions(), { ...list, recipes: [CHECKS] })
  const edge = (id: string) => document.querySelector(`.react-flow__edge[data-id="${id}"]`)
  await waitFor(() => expect(edge('fork-build')).not.toBeNull())
  for (const id of ['fork-docs', 'join-test', 'join-docs']) expect(edge(id)).not.toBeNull()
  expect(edge('fork-test')).toBeNull() // Test it comes after Build it in its branch, not from the fork
  expect(screen.getByText('first done')).toBeInTheDocument()
})

test('Tidy up lays a group stacked in one column out in its branches’ columns (B-374)', async () => {
  // Saved as the board drew it before: one under another.
  const stacked = (['build', 'test', 'docs'] as const).reduce((graph, id, at) => place(graph, id, { x: 12, y: 30 + at * 58 }), CHECKS.graph)
  const given = draw(actions(), { ...list, recipes: [{ ...CHECKS, ready: false, graph: stacked }] })
  expect(new Set(['build', 'test', 'docs'].map(id => layout(stacked)[id].x)).size).toBe(1)
  fireEvent.click(screen.getByRole('button', { name: 'Tidy up' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  const places = layout(body.graph)
  expect(places.docs.x).not.toBe(places.build.x)
  expect(places.test.x).toBe(places.build.x)
})

test('B-375: the one line shows a fork’s ways side by side, then where they meet', () => {
  // R172: Checks (Build it → Test it, Write docs) and All at once (two steps), both from the start to the end.
  const twoGroups: RecipeGraph = {
    ...emptyGraph(),
    steps: [
      step('build', 'Build it', { group: 'g' }),
      step('test', 'Test it', { group: 'g' }),
      step('docs', 'Write docs', { group: 'g' }),
      step('f1', 'First', { group: 'g1' }),
      step('f2', 'Second', { group: 'g1' }),
    ],
    groups: [
      { id: 'g', name: 'Checks', wait: 'first' },
      { id: 'g1', name: 'All at once', wait: 'all' },
    ],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [[START, 'g'], [START, 'g1'], ['build', 'test'], ['g', 'end'], ['g1', 'end']].map(([from, to]) => ({ from, to })),
  }
  expect(summary(twoGroups)).toBe('(3 at once ∥ 2 at once) → Ask me, then in')
  // A step forking into a line of two and one, met at a third.
  const diamond: RecipeGraph = {
    ...emptyGraph(),
    steps: [step('a', 'Build it'), step('b', 'Test it'), step('b2', 'Fix it'), step('c', 'Write docs'), step('d', 'Review')],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [['start', 'a'], ['a', 'b'], ['a', 'c'], ['b', 'b2'], ['b2', 'd'], ['c', 'd'], ['d', 'end']].map(([from, to]) => ({ from, to })),
  }
  expect(summary(diamond)).toBe('Build it → (Test it → Fix it ∥ Write docs) → Review → Ask me, then in')
})

test('parts no arrow from the start reaches are laid out under it along their own arrows, no row wider than four (B-108)', () => {
  const ten = Array.from({ length: 10 }, (_, at) => step(`s${at + 1}`, `Step ${at + 1}`))
  const arrows = [...ten.slice(1).map((one, at) => ({ from: ten[at].id, to: one.id })), { from: 's10', to: 'end' }]
  const loose: RecipeGraph = { version: 1, steps: ten, groups: [], ends: [{ id: 'end', then: 'in' }], arrows, loops: [] }
  const places = layout(loose)
  expect(places.s1.y).toBeGreaterThan(places.start.y)
  for (let at = 1; at < 10; at++) expect(places[`s${at + 1}`].y).toBeGreaterThan(places[`s${at}`].y)
  const across = (all: ReturnType<typeof layout>) => Math.max(...Object.values(all).map(one => one.x + one.w)) - Math.min(...Object.values(all).map(one => one.x))
  expect(across(places)).toBe(200)
  // Not joined at all: four to a row, and the end, joined to nothing, at the bottom.
  const apart = layout({ ...loose, arrows: [] })
  expect(across(apart)).toBeLessThanOrEqual(4 * 200 + 3 * 34)
  expect(apart.end.y).toBeGreaterThan(Math.max(...ten.map(one => apart[one.id].y)))
  // Five the start leads to, side by side: one row.
  const five = layout({ ...loose, steps: ten.slice(0, 5), arrows: ten.slice(0, 5).map(one => ({ from: START, to: one.id })), ends: [] })
  expect(new Set(ten.slice(0, 5).map(one => five[one.id].y)).size).toBe(1)
})

test('a part dragged stays where it was put, the rest laid out as before; Tidy up gives every part back to the board', () => {
  const auto = layout(FEATURE.graph)
  const moved = place(place(FEATURE.graph, 'g', { x: 500, y: 40 }), 'ui', { x: 12, y: 0 })
  const places = layout(moved)
  expect(places.g).toEqual({ ...auto.g, x: 500, y: 40 })
  expect(places.ui).toEqual({ ...auto.ui, x: 12, y: 0 }) // from its group's corner
  expect([places.start, places.build, places.end, places.code]).toEqual([auto.start, auto.build, auto.end, auto.code])
  expect(layout(tidy(moved))).toEqual(auto)
  // Put in a group or taken out of one, a step is placed by the board again: a group's step is placed from its corner.
  const out = changeStep(moved, 'ui', { group: null })
  expect(out.steps.find(one => one.id === 'ui')?.pos).toBeNull()
  expect(changeStep(moved, 'ui', { name: 'Look at it' }).steps.find(one => one.id === 'ui')?.pos).toEqual({ x: 12, y: 0 })
})

test('a loop back is a curve from one right side to the other, its words just past the curve, not on it', () => {
  // From a group's right side (x 112, low) back up to a step's (x 100).
  const { path, labelX, labelY } = loopCurve(112, 300, 100, 120)
  expect(path).toBe('M112,300 C157,300 157,120 100,120') // ends on the step's side, coming in from the right
  // The curve's farthest point is at its middle: 1/8 of each end and 3/4 of the bend, 144.25; the words start just past it.
  expect(labelX).toBeGreaterThan(144.25)
  expect(labelX).toBeLessThan(152)
  expect(labelY).toBe(210)
})

test('the steps of a group have arrows of their own only inside it (K-tarif-kol: its branches); the group is joined', () => {
  draw()
  const inGroup = (name: string) => document.querySelector(`.react-flow__node[data-id="${name}"]`) as HTMLElement
  expect(inGroup('code').querySelector('[data-handleid="out"]')).not.toBeNull()
  expect(targets(FEATURE.graph, 'code')).toEqual(['ui'])
  expect(inGroup('g').querySelector('[data-handleid="in"]')).not.toBeNull()
  expect(inGroup('build').querySelector('[data-handleid="out"]')).not.toBeNull()
  // A loop may still leave or reach a group's step: its side's handles stay (unseen).
  expect(inGroup('code').querySelector('[data-handleid="loop-out"]')).not.toBeNull()
  // An arrow is drawn only from where it leaves (B-85): the right side's source over its target, which starts none.
  expect(inGroup('build').querySelector('[data-handleid="in"]')).not.toHaveClass('connectablestart')
  expect(inGroup('build').querySelector('[data-handleid="loop-in"] ~ [data-handleid="loop-out"]')).not.toBeNull()
})

test('a group’s default name says what it waits for, both ways; a name the user typed stays', () => {
  const [graph, g] = addGroup(emptyGraph(), null)
  const first = waitOn(graph, g, 'first')
  expect(first.groups[0]).toMatchObject({ wait: 'first', name: 'All at once, first one done' })
  expect(waitOn(first, g, 'all').groups[0]).toMatchObject({ wait: 'all', name: 'All at once, wait for all' })
  const named = renameGroup(graph, g, 'Checks')
  expect(waitOn(named, g, 'first').groups[0]).toMatchObject({ wait: 'first', name: 'Checks' })
  expect(waitOn(waitOn(named, g, 'first'), g, 'all').groups[0].name).toBe('Checks')
})

test('a step added is named apart from the others', () => {
  let [graph] = addStep(emptyGraph(), START)
  ;[graph] = addStep(graph, null)
  ;[graph] = addGroup(addGroup(graph, null)[0], null)
  expect(graph.steps.map(one => one.name)).toEqual(['New step', 'New step 2', 'First at once', 'Second at once', 'First at once 2', 'Second at once 2'])
})

// --- the tab ----------------------------------------------------------------------------------------------------------------------

test('a ready recipe is drawn read-only and copied to be changed', async () => {
  const given = draw()
  expect(screen.getByRole('button', { name: /^Feature/ })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: '+ Step' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Save recipe' })).toBeNull()
  fireEvent.click(part(/^Build it/))
  expect(within(panel()).getByLabelText('Who')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  expect(screen.getByLabelText('Recipe’s name')).toHaveValue('Feature copy')
  expect(screen.getByRole('button', { name: '+ Step' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalledWith(null, { name: 'Feature copy', graph: FEATURE.graph }, null))
})

test('a step says, before any run, where its role cannot be a step, and a room where a member cannot be in one (B-89)', () => {
  const models = {
    Reviewer: { cannot_run: null, cannot_step: 'agy works with tools of its own in the project itself', cannot_room: null },
    Coder: { cannot_run: null, cannot_step: null, cannot_room: 'Codex works with tools of its own here' },
  } as unknown as Record<string, RoleModel>
  const talk: Recipe = { ...FEATURE, id: 'talk', graph: { ...FEATURE.graph, steps: [...FEATURE.graph.steps, step('room', 'Talk it over', { who: { room: ['Coder', 'Reviewer'] } })] } }
  render(<RecipesTab roles={roles} teams={teams} list={{ ...list, recipes: [talk] }} projectId={null} actions={actions()} reload={vi.fn()} models={models} />)
  const warned = () => within(panel()).queryByRole('list', { name: 'Will not run' })?.textContent ?? null
  fireEvent.click(part(/^Code review/))
  expect(warned()).toBe('⚠ Reviewer: Not as a recipe’s step: agy works with tools of its own in the project itself')
  fireEvent.click(part(/^Build it/))
  expect(warned()).toBeNull() // (a Coder may be a step; its room's warning is no step's)
  fireEvent.click(part(/^Talk it over/))
  expect(warned()).toBe('⚠ Coder: Not in a room: Codex works with tools of its own here')
})

test('a ready recipe’s parts stay where they are; a copy’s are dragged, and Tidy up is saved like any change', async () => {
  const arranged: Recipe = { ...FEATURE, id: 'mine', ready: false, graph: place(FEATURE.graph, 'build', { x: 300, y: 90 }) }
  const given = draw(actions(), { ...list, recipes: [FEATURE, arranged] })
  const node = (id: string) => document.querySelector(`.react-flow__node[data-id="${id}"]`) as HTMLElement
  expect(node('build')).not.toHaveClass('draggable')
  expect(screen.getByRole('button', { name: 'Tidy up' })).toBeDisabled()
  fireEvent.click(screen.getAllByRole('button', { name: /^Feature/ })[1])
  expect(node('build')).toHaveClass('draggable')
  expect(node('start')).not.toHaveClass('draggable')
  expect(node('build').style.transform).toBe('translate(300px,90px)')
  fireEvent.click(screen.getByRole('button', { name: 'Tidy up' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalledWith(arranged, { name: 'Feature', graph: tidy(arranged.graph) }, null))
  expect(tidy(arranged.graph).steps.every(one => one.pos === null)).toBe(true)
})

test('a recipe drawn: steps added and connected, its Who, a loop’s round limit, then saved', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  // The new step is chosen: named, given to a role.
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Code it' } })
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'role:Coder' } })
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Review it' } })
  fireEvent.change(within(panel()).getByLabelText('Done when'), { target: { value: 'no_findings' } })
  fireEvent.click(screen.getByRole('button', { name: '+ Loop back' }))
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'At most' }), { target: { value: '3' } })
  expect(within(panel()).getByLabelText('Loops back to')).toHaveDisplayValue('to Code it, with the findings')
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  // An arrow drawn from the panel: from the start to the end as well, then taken away.
  fireEvent.click(part(/^Your message/))
  fireEvent.change(within(panel()).getByLabelText('Add an arrow to'), { target: { value: 'end1' } })
  fireEvent.click(within(panel()).getByRole('button', { name: 'No arrow to Ask me, then in' }))
  fireEvent.change(screen.getByLabelText('Recipe’s name'), { target: { value: 'Mine' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.name).toBe('Mine')
  expect(body.graph.steps.map((one: { name: string; who: unknown }) => [one.name, one.who])).toEqual([
    ['Code it', { role: 'Coder' }],
    ['Review it', { lead: true }],
  ])
  expect(body.graph.arrows).toEqual([
    { from: 'start', to: 's1' },
    { from: 's1', to: 's2' },
    { from: 's2', to: 'end1' },
  ])
  expect(body.graph.loops).toEqual([{ from: 's2', to: 's1', rounds: 3 }])
  expect(await screen.findByText('Saved.')).toBeVisible()
})

test('a step marked to run only if the step before found a problem says so on its card, and is saved so', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Fix it' } })
  const only = within(panel()).getByLabelText('Only if the step before found a problem')
  expect(only).not.toBeChecked()
  fireEvent.click(only)
  expect(part(/^Fix it/)).toHaveTextContent('only if the step before found a problem')
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.graph.steps).toMatchObject([{ name: 'Fix it', when: 'problem' }])
})

test('K-rol-cogul: a role’s step draws at most 1 to 5 of it, said on its card; 1 is not written; no other Who has it', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Build it' } })
  expect(within(panel()).queryByLabelText('At most of its role')).toBeNull()
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'role:Coder' } })
  const most = within(panel()).getByRole('combobox', { name: 'At most of its role' })
  expect(most).toHaveValue('1')
  expect(within(most).getAllByRole('option').map(one => one.textContent)).toEqual(['1 agent', '2 agents', '3 agents', '4 agents', '5 agents'])
  fireEvent.change(most, { target: { value: '2' } })
  expect(part(/^Build it/)).toHaveTextContent('Coder, up to 2')
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.graph.steps[0].who).toEqual({ role: 'Coder', most: 2 })
  fireEvent.click(part(/^Build it/))
  fireEvent.change(within(panel()).getByLabelText('At most of its role'), { target: { value: '1' } })
  expect(part(/^Build it/)).not.toHaveTextContent('up to')
})

test('K-evrim: a step of candidates of a role, 2 to 5 of them, said on its card and saved so', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Build it' } })
  expect(within(panel()).queryByLabelText('At most candidates')).toBeNull()
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'candidates:Coder' } })
  const most = within(panel()).getByRole('combobox', { name: 'At most candidates' })
  expect(most).toHaveValue('2')
  expect(within(most).getAllByRole('option').map(one => one.textContent)).toEqual(['2 candidates', '3 candidates', '4 candidates', '5 candidates'])
  fireEvent.change(most, { target: { value: '3' } })
  expect(part(/^Build it/)).toHaveTextContent('Candidates')
  expect(part(/^Build it/)).toHaveTextContent('Coder ×3')
  expect(within(panel()).queryByLabelText('At most of its role')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.graph.steps[0].who).toEqual({ candidates: 'Coder', most: 3, models: 'auto' })
})

test('K-evrim: a step of candidates has a target and may go round again itself; no other step may', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Build it' } })
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'role:Coder' } })
  const loops = () => within(within(panel()).getByLabelText('Loops back to')).getAllByRole('option').map(one => one.textContent)
  expect(loops()).not.toContain('round again, from the picked one’s work')
  expect(within(panel()).queryByLabelText('Target score')).toBeNull()
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'candidates:Coder' } })
  expect(loops()).toContain('round again, from the picked one’s work')
  fireEvent.change(within(panel()).getByLabelText('Target score'), { target: { value: '80' } })
  const id = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls.length
  fireEvent.change(within(panel()).getByLabelText('Loops back to'), { target: { value: within(within(panel()).getByLabelText('Loops back to')).getByText('round again, from the picked one’s work').getAttribute('value') } })
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'At most' }), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect((given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls.length).toBe(id + 1))
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[id]
  const build = body.graph.steps[0]
  expect(build.who).toEqual({ candidates: 'Coder', most: 2, target: 80, models: 'auto' })
  expect(body.graph.loops).toEqual([{ from: build.id, to: build.id, rounds: 3 }])
})

test('K-evrim-model: the candidates’ models are the Lead’s, the same, or yours for each - from providers agents may use', async () => {
  const providers = [
    { id: 'local', name: 'Local', for_agents: true, default_model: 'big-model' },
    { id: 'fast', name: 'Fast', for_agents: true, default_model: 'quick' },
    { id: 'off', name: 'Off', for_agents: false, default_model: null },
  ] as Provider[]
  const given = actions()
  const onModels = vi.fn().mockResolvedValue({ models: ['quick', 'deep'], note: null })
  render(<RecipesTab roles={roles} teams={teams} list={list} projectId={null} actions={given} reload={vi.fn()} providers={providers} onModels={onModels} />)
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Name'), { target: { value: 'Build it' } })
  expect(within(panel()).queryByRole('combobox', { name: 'Models' })).toBeNull()
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'candidates:Coder' } })
  const how = within(panel()).getByRole('combobox', { name: 'Models' })
  expect(how).toHaveValue('auto')
  expect(within(how).getAllByRole('option').map(one => one.textContent)).toEqual(['Auto, the Lead picks', 'Same model', 'I pick each'])
  expect(within(panel()).queryByRole('group', { name: 'Each candidate’s model' })).toBeNull()
  fireEvent.change(how, { target: { value: 'each' } })
  const each = () => within(panel()).getByRole('group', { name: 'Each candidate’s model' })
  // One picker each, its providers those agents may use; its models suggested by the provider's list.
  const first = within(each()).getByRole('combobox', { name: 'Candidate 1’s provider' })
  expect(within(first).getAllByRole('option').map(one => one.textContent)).toEqual(['Local', 'Fast'])
  fireEvent.change(first, { target: { value: 'fast' } })
  await waitFor(() => expect(onModels).toHaveBeenCalledWith('fast'))
  fireEvent.change(within(each()).getByLabelText('Candidate 1’s model'), { target: { value: 'deep' } })
  fireEvent.click(within(each()).getByRole('button', { name: '+ Candidate 2' }))
  fireEvent.change(within(each()).getByRole('combobox', { name: 'Candidate 2’s provider' }), { target: { value: 'local' } })
  // Up to as many as it takes: one past "At most" is cut as it goes down.
  expect(within(each()).queryByRole('button', { name: '+ Candidate 3' })).toBeNull()
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'At most candidates' }), { target: { value: '3' } })
  fireEvent.click(within(each()).getByRole('button', { name: '+ Candidate 3' }))
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'At most candidates' }), { target: { value: '2' } })
  expect(within(each()).queryByLabelText('Candidate 3’s model')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.graph.steps[0].who).toEqual({
    candidates: 'Coder',
    most: 2,
    models: [
      { provider_id: 'fast', model_id: 'deep' },
      { provider_id: 'local', model_id: null },
    ],
  })
  fireEvent.click(part(/^Build it/))
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'Models' }), { target: { value: 'same' } })
  expect(within(panel()).queryByRole('group', { name: 'Each candidate’s model' })).toBeNull()
})

test('B-388: I pick each offers no provider whose agent of the role works in the project itself, not a copy', () => {
  const providers = [
    { id: 'agy', name: 'agy', for_agents: true, default_model: 'flash' },
    { id: 'local', name: 'Local', for_agents: true, default_model: 'big-model' },
  ] as Provider[]
  // (What the Agents page's table says each provider would be for the role: `step` false, as the spawn refuses it.)
  const models = {
    Coder: {
      cannot_run: null,
      cannot_step: null,
      cannot_room: null,
      run_on: [
        { provider_id: 'agy', model_id: 'flash', step: false, room: true },
        { provider_id: 'local', model_id: 'big-model', step: true, room: true },
      ],
    },
  } as unknown as Record<string, RoleModel>
  render(<RecipesTab roles={roles} teams={teams} list={list} projectId={null} actions={actions()} reload={vi.fn()} providers={providers} models={models} />)
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Step' }))
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'candidates:Coder' } })
  fireEvent.change(within(panel()).getByRole('combobox', { name: 'Models' }), { target: { value: 'each' } })
  const first = within(panel()).getByRole('combobox', { name: 'Candidate 1’s provider' })
  expect(first).toHaveValue('local') // (the first that can run in a copy)
  const [agy, local] = within(first).getAllByRole('option') as HTMLOptionElement[]
  expect([agy.textContent, agy.disabled]).toEqual(['agy (can’t run in a recipe’s copy)', true])
  expect([local.textContent, local.disabled]).toEqual(['Local', false])
})

test('a room (slice 84e): never in a group, after the chosen part; its roles ticked in its panel, then saved', async () => {
  let [graph, group] = addGroup(emptyGraph(), START)
  let room: string
  ;[graph, room] = addRoom(graph, group)
  expect(graph.steps.find(one => one.id === room)).toMatchObject({ who: { room: [] }, group: null })
  expect(graph.arrows).toContainEqual({ from: group, to: room })
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ Room' }))
  const who = within(panel()).getByRole('group', { name: 'Who meets in the room' })
  fireEvent.click(within(who).getByLabelText('Coder'))
  fireEvent.click(within(who).getByLabelText('Reviewer'))
  // A room meets on its own; it ends by its own rules.
  expect(within(panel()).queryByLabelText('At the same time as')).toBeNull()
  expect(within(panel()).getByLabelText('Done when')).toHaveDisplayValue('the room ends: all say done, or its time or budget is up')
  expect(part(/^Meeting/)).toHaveTextContent('Coder · Reviewer')
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  expect(body.graph.steps).toMatchObject([{ name: 'Meeting', who: { room: ['Coder', 'Reviewer'] } }])
  expect(body.graph.arrows).toEqual([
    { from: 'start', to: 's1' },
    { from: 's1', to: 'end1' },
  ])
})

test('K-tarif-kol: a group’s step goes on to another of its group, one line, never round; out of the group its arrows go', () => {
  let [graph, g] = addGroup(emptyGraph(), START)
  const [a, b] = graph.steps.map(step => step.id)
  let c: string
  ;[graph, c] = addStep(graph, g)
  expect(targets(graph, a)).toEqual([b, c]) // its group's steps only: no end, no step outside
  graph = connect(graph, a, b)
  expect(targets(graph, a)).toEqual([]) // one arrow out
  expect(targets(graph, c)).toEqual([a]) // b has its one arrow in
  expect(targets(graph, b)).toEqual([c]) // not back to a: that would go round
  expect(connect(graph, b, a)).toBe(graph)
  expect(changeStep(graph, b, { group: null }).arrows).toEqual([{ from: START, to: g }])
})

test('K-tarif-kol: an arrow drawn inside a group from its step’s panel, and the group waits for the first one done; both saved', async () => {
  const given = draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ All at once' }))
  expect(within(panel()).getByLabelText('Wait for')).toHaveDisplayValue('all branches')
  expect(panel()).toHaveTextContent('Steps at the same time, all done before it goes on')
  fireEvent.change(within(panel()).getByLabelText('Wait for'), { target: { value: 'first' } })
  expect(panel()).toHaveTextContent('the others are stopped; what they already changed stays in the work')
  fireEvent.click(part(/^First at once/))
  const add = within(panel()).getByLabelText('Add an arrow to')
  expect(within(add).getAllByRole('option').map(one => one.textContent)).toEqual(['+ an arrow to…', 'Second at once'])
  fireEvent.change(add, { target: { value: within(add).getByText('Second at once').getAttribute('value') } })
  fireEvent.click(part(/^Second at once/))
  expect(panel()).toHaveTextContent('the work of First at once')
  fireEvent.click(part(/^All at once, first one done/)) // (its default name says it)
  fireEvent.click(screen.getByRole('button', { name: '+ Ask me' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  await waitFor(() => expect(given.saveRecipe).toHaveBeenCalled())
  const [, body] = (given.saveRecipe as ReturnType<typeof vi.fn>).mock.calls[0]
  const [first, second] = body.graph.steps.map((step: { id: string }) => step.id)
  expect(body.graph.arrows).toContainEqual({ from: first, to: second })
  expect(body.graph.groups[0]).toMatchObject({ wait: 'first', name: 'All at once, first one done' })
})

test('steps at the same time: a group from the toolbar, a step moved into it from its panel', () => {
  draw()
  fireEvent.click(screen.getByRole('button', { name: '+ Draw a new recipe' }))
  fireEvent.click(part(/^Your message/))
  fireEvent.click(screen.getByRole('button', { name: '+ All at once' }))
  expect(part(/^First at once/)).toBeVisible()
  expect(part(/^Second at once/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '+ Step' })) // the group chosen: a third step in it
  expect(within(panel()).getByLabelText('At the same time as')).toHaveDisplayValue('in “All at once, wait for all”')
  fireEvent.change(within(panel()).getByLabelText('At the same time as'), { target: { value: '' } })
  expect(within(panel()).getByLabelText('At the same time as')).toHaveDisplayValue('no: on its own')
})

test('a recipe of yours is deleted only once you say so again: a team that ran by it has no default then', async () => {
  const mine: Recipe = { ...FEATURE, id: 'mine', name: 'Mine', ready: false }
  const given = draw(actions(), { ...list, recipes: [FEATURE, mine] })
  fireEvent.click(screen.getByRole('button', { name: /^Mine/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  expect(screen.getByText(/Delete Mine\? A team that runs by it will have no default recipe/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(given.deleteRecipe).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete recipe' }))
  await waitFor(() => expect(given.deleteRecipe).toHaveBeenCalledWith(mine))
})

test('what the server says keeps it from running is shown at its step', async () => {
  const refused = new ApiError(422, 'Build it: “Wizard” is no role here; The recipe has no end: add one (+ Ask me)', [
    { loc: ['body', 'graph'], msg: 'Build it: “Wizard” is no role here', at: 'build' },
    { loc: ['body', 'graph'], msg: 'The recipe has no end: add one (+ Ask me)', at: null },
  ])
  draw(actions({ saveRecipe: vi.fn().mockRejectedValue(refused) }))
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  // (R57: the first part it is about is chosen, its words in its panel - none under the node, over its arrows)
  expect(await screen.findByText('Build it: “Wizard” is no role here')).toBeVisible()
  expect(within(panel()).getByRole('alert')).toHaveTextContent('“Wizard” is no role here')
  expect(screen.getAllByRole('alert').map(one => one.textContent)).toContain('The recipe has no end: add one (+ Ask me)')
  // (the node's ⚠ comes in React Flow's own update after the words: on a busy machine, a moment later)
  await waitFor(() => expect(document.querySelector('.react-flow__node[data-id="build"] [role="img"]')).toHaveAccessibleName('Build it: “Wizard” is no role here'))
  expect(document.querySelector('.react-flow__node[data-id="build"]')).not.toHaveTextContent('Wizard')
})

test('B-375: a fork the runner cannot run is said at the part it forks from, Your message too', async () => {
  const msg = 'Your message: its ways run at once and meet again at one part, which waits for all of them (an end may be it)'
  draw(actions({ saveRecipe: vi.fn().mockRejectedValue(new ApiError(422, msg, [{ loc: ['body', 'graph'], msg, at: 'start' }])) }))
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  expect(await screen.findByText(msg)).toBeVisible()
  await waitFor(() => expect(document.querySelector('.react-flow__node[data-id="start"] [role="img"]')).toHaveAccessibleName(msg))
})

test('B-196: the condition the server refused taken off its step, the step’s ⚠ and “It cannot run yet” go', async () => {
  const refused = new ApiError(422, 'refused', [{ loc: ['body', 'graph'], msg: 'Build it: the first step has no step before it', at: 'build' }])
  draw(actions({ saveRecipe: vi.fn().mockRejectedValue(refused) }))
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  fireEvent.click(part(/^Build it/))
  fireEvent.click(within(panel()).getByLabelText('Only if the step before found a problem'))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  expect(await screen.findByText('It cannot run yet: one part says why.')).toBeVisible()
  const sign = () => document.querySelector('.react-flow__node[data-id="build"] [role="img"]')
  await waitFor(() => expect(sign()).not.toBeNull())
  fireEvent.click(within(panel()).getByLabelText('Only if the step before found a problem'))
  expect(screen.queryByText('It cannot run yet: one part says why.')).toBeNull()
  expect(within(panel()).queryByRole('alert')).toBeNull()
  expect(sign()).toBeNull()
})

test('a step whose role cannot be a step there shows ⚠ on its node, with why (B-108)', () => {
  const models = { Reviewer: { cannot_run: null, cannot_step: 'agy works with tools of its own in the project itself', cannot_room: null } } as unknown as Record<string, RoleModel>
  render(<RecipesTab roles={roles} teams={teams} list={list} projectId={null} actions={actions()} reload={vi.fn()} models={models} />)
  const sign = (id: string) => document.querySelector(`.react-flow__node[data-id="${id}"] [role="img"]`)
  expect(sign('code')).toHaveAccessibleName('Reviewer: Not as a recipe’s step: agy works with tools of its own in the project itself')
  expect(sign('build')).toBeNull()
})

test('a step left with no name is said at it in plain words, not as the request’s field (B-108)', async () => {
  const refused = new ApiError(422, "graph.steps.0.name: Value error, a step's name is 1 to 60 printable characters", [
    { loc: ['body', 'graph', 'steps', 0, 'name'], msg: "Value error, a step's name is 1 to 60 printable characters", type: 'value_error' },
  ])
  draw(actions({ saveRecipe: vi.fn().mockRejectedValue(refused) }))
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  expect(await screen.findByText("A step's name is 1 to 60 printable characters")).toBeVisible()
  expect(screen.queryByText(/Value error|graph\.steps/)).toBeNull()
  await waitFor(() => expect(document.querySelector('.react-flow__node[data-id="build"] [role="img"]')).toHaveAccessibleName("A step's name is 1 to 60 printable characters"))
})

test('an empty recipe name is said in plain words, a Who the board does not draw in one line at its step, an empty word breaks nothing', async () => {
  const refused = new ApiError(422, 'refused', [
    { loc: ['body', 'name'], msg: "Value error, a recipe's name is 1 to 60 printable characters", type: 'value_error' },
    { loc: ['body', 'graph', 'steps', 0, 'who', 'WhoRole', 'role'], msg: 'Field required', type: 'missing' },
    { loc: ['body', 'graph', 'steps', 0, 'who', 'WhoTeam', 'team'], msg: 'Field required', type: 'missing' },
    { loc: ['body', 'graph', 'groups', 0, 'name'], msg: '', type: 'value_error' },
  ])
  draw(actions({ saveRecipe: vi.fn().mockRejectedValue(refused) }))
  fireEvent.click(screen.getByRole('button', { name: 'Copy it' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save recipe' }))
  expect(await screen.findByText("A recipe's name is 1 to 60 printable characters")).toBeVisible()
  await waitFor(() => expect(document.querySelector('.react-flow__node[data-id="build"] [role="img"]')).toHaveAccessibleName('Who does it is not one the board draws: choose it again'))
  expect(screen.queryByText(/Field required/)).toBeNull()
})

test('or write it: the Lead’s model draws a draft on the board, saved by nobody; with no model the button says why', async () => {
  const drawn = { name: 'Spec first', graph: { ...FEATURE.graph, loops: [] }, provider_name: 'Local', model_id: 'qwen' }
  const given = draw(actions({ draftRecipe: vi.fn().mockResolvedValue(drawn) }))
  const make = screen.getByRole('button', { name: 'Make it a recipe' })
  expect(make).toBeDisabled()
  fireEvent.change(screen.getByLabelText('The recipe in words'), { target: { value: 'spec, then code' } })
  fireEvent.click(make)
  await waitFor(() => expect(screen.getByLabelText('Recipe’s name')).toHaveValue('Spec first'))
  expect(given.draftRecipe).toHaveBeenCalledWith('spec, then code')
  expect(screen.getByRole('status')).toHaveTextContent('Drawn by Local (qwen)')
  expect(given.saveRecipe).not.toHaveBeenCalled()
})

test('with no model to ask, "Make it a recipe" is off and says why', () => {
  draw(actions(), { ...list, writer: { why: 'There is no model to ask: add a provider on the Models page.' } })
  fireEvent.change(screen.getByLabelText('The recipe in words'), { target: { value: 'spec, then code' } })
  expect(screen.getByRole('button', { name: 'Make it a recipe' })).toBeDisabled()
  expect(screen.getByText('There is no model to ask: add a provider on the Models page.')).toBeVisible()
})

test('K-uzman: a step of the team’s experts says whose, and its Who keeps it', () => {
  const integration: Recipe = {
    ...FEATURE,
    id: 'integration',
    name: 'Integration',
    graph: {
      version: 1,
      steps: [step('learn', 'Learn', { who: { experts: 'stale' } }), step('check', 'Experts check the plan', { who: { experts: 'all' }, done_when: 'no_findings' })],
      groups: [],
      ends: [{ id: 'end', then: 'in' }],
      arrows: [
        { from: 'start', to: 'learn' },
        { from: 'learn', to: 'check' },
        { from: 'check', to: 'end' },
      ],
      loops: [],
    },
  }
  draw(actions(), { ...list, recipes: [integration] })
  expect(part(/^Learn/)).toHaveTextContent('the team’s experts whose guide is old: they learn')
  fireEvent.click(part(/^Experts check the plan/))
  expect(within(panel()).getByLabelText('Who')).toHaveValue('experts:all')
  // K-takim-duzen: only those that have learned - Model change's review of the plan.
  fireEvent.change(within(panel()).getByLabelText('Who'), { target: { value: 'experts:learned' } })
  expect(within(panel()).getByLabelText('Who')).toHaveValue('experts:learned')
  expect(part(/^Experts check the plan/)).toHaveTextContent('the team’s experts that have learned, at once')
})
