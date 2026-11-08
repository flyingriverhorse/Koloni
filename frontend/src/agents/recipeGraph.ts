import type { RecipeGraph, RecipeStep, Role, Team } from '../api/types'

/**
 * A recipe's drawing as the board changes it (slice 84a): pure functions of the graph the server keeps, each giving a new one. What
 * makes a drawing one that can run is the server's to say, as it is saved (`app.recipes.problems`).
 */

export type Who = RecipeStep['who']
export type End = RecipeGraph['ends'][number]
/** The user's message: where every recipe begins (no part of the graph of its own). */
export const START = 'start'
export const START_NAME = 'Your message'
export const END_NAMES: Record<End['then'], string> = { in: 'Ask me, then in', report: 'Tell me what was found' }
export const GROUP_NAME = 'All at once, wait for all'
const FIRST_NAME = 'All at once, first one done'
const ROUNDS = 2

export const emptyGraph = (): RecipeGraph => ({ version: 1, steps: [], groups: [], ends: [], arrows: [], loops: [] })

export type Kind = 'start' | 'step' | 'group' | 'end'
export function kindOf(graph: RecipeGraph, id: string): Kind | null {
  if (id === START) return 'start'
  if (graph.steps.some(step => step.id === id)) return 'step'
  if (graph.groups.some(group => group.id === id)) return 'group'
  return graph.ends.some(end => end.id === id) ? 'end' : null
}

export function nameOf(graph: RecipeGraph, id: string): string {
  if (id === START) return START_NAME
  const end = graph.ends.find(one => one.id === id)
  return end ? END_NAMES[end.then] : ([...graph.steps, ...graph.groups].find(one => one.id === id)?.name ?? id)
}

const stepOf = (graph: RecipeGraph, id: string) => graph.steps.find(step => step.id === id)

/** Whether an arrow may leave it: the start, a step, a group (a step in a group only to another of its group: K-tarif-kol). */
export function goesOn(graph: RecipeGraph, id: string | null): id is string {
  if (id === null) return false
  const kind = kindOf(graph, id)
  return kind === 'start' || kind === 'group' || kind === 'step'
}

/** K-tarif-kol: where a group's step may go on to in its branch - another step of its group that nothing comes to yet, not the
 * first of its own branch (that would go round); none once it has its one arrow out. */
function inBranch(graph: RecipeGraph, from: string, group: string): string[] {
  if (graph.arrows.some(arrow => arrow.from === from)) return []
  const line = new Set([from])
  for (let at = from, arrow; (arrow = graph.arrows.find(one => one.to === at)) && !line.has(arrow.from); at = arrow.from) line.add(arrow.from)
  return graph.steps.filter(step => step.group === group && !line.has(step.id) && !graph.arrows.some(arrow => arrow.to === step.id)).map(step => step.id)
}

/** Where a part stands on the way: a step in a group stands as its group. */
const onTheWay = (graph: RecipeGraph, id: string) => stepOf(graph, id)?.group ?? id

/** The parts on the way to `id`: each one an arrow, or arrows, lead from to it. */
function ancestors(graph: RecipeGraph, id: string): Set<string> {
  const found = new Set<string>()
  const todo = [onTheWay(graph, id)]
  while (todo.length) {
    const at = todo.pop()
    for (const arrow of graph.arrows)
      if (arrow.to === at && !found.has(arrow.from)) {
        found.add(arrow.from)
        todo.push(arrow.from)
      }
  }
  return found
}

/**
 * Where an arrow from `from` may go next: a step outside a group, a group or an end - not one it goes to already, nor one on the way
 * to it (going back is a loop's, which has a round limit).
 */
export function targets(graph: RecipeGraph, from: string): string[] {
  const group = stepOf(graph, from)?.group
  if (group) return inBranch(graph, from, group)
  const taken = new Set([from, ...ancestors(graph, from), ...graph.arrows.filter(arrow => arrow.from === from).map(arrow => arrow.to)])
  return [...graph.steps.filter(step => !step.group).map(step => step.id), ...graph.groups.map(group => group.id), ...graph.ends.map(end => end.id)].filter(
    id => !taken.has(id),
  )
}

/** Where a loop from `from` may go back to: a step or group on the way to it - never inside its own group. */
export function loopTargets(graph: RecipeGraph, from: string): string[] {
  const back = ancestors(graph, from)
  // K-evrim: a step of candidates goes round again itself, from the picked one's work.
  const again = graph.steps.some(step => step.id === from && 'candidates' in step.who) ? [from] : []
  return [
    ...again,...graph.steps.filter(step => back.has(onTheWay(graph, step.id))).map(step => step.id), ...graph.groups.filter(group => back.has(group.id)).map(group => group.id)]
}

function fresh(graph: RecipeGraph, prefix: string): string {
  const taken = new Set([START, ...graph.steps.map(one => one.id), ...graph.groups.map(one => one.id), ...graph.ends.map(one => one.id)])
  let n = 1
  while (taken.has(`${prefix}${n}`)) n += 1
  return `${prefix}${n}`
}

/** A name no step has yet ("New step 2"): each told apart on the board and in its panel. */
function unnamed(graph: RecipeGraph, name: string): string {
  let n = 1
  while (graph.steps.some(step => step.name === (n === 1 ? name : `${name} ${n}`))) n += 1
  return n === 1 ? name : `${name} ${n}`
}

const newStep = (graph: RecipeGraph, id: string, name: string, group: string | null = null): RecipeStep => ({
  id,
  name: unnamed(graph, name),
  who: { lead: true },
  done_when: 'done',
  if_fails: 'ask',
  ask_me: false,
  group,
})

export function connect(graph: RecipeGraph, from: string, to: string): RecipeGraph {
  if (!goesOn(graph, from) || !targets(graph, from).includes(to)) return graph
  return { ...graph, arrows: [...graph.arrows, { from, to }] }
}

export const disconnect = (graph: RecipeGraph, from: string, to: string): RecipeGraph => ({
  ...graph,
  arrows: graph.arrows.filter(arrow => !(arrow.from === from && arrow.to === to)),
})

/** A new step: in the group that is chosen (or whose step is), else after the part that is chosen (an arrow from it, where one may leave it). */
export function addStep(graph: RecipeGraph, after: string | null): [RecipeGraph, string] {
  const id = fresh(graph, 's')
  const inGroup = after === null ? null : kindOf(graph, after) === 'group' ? after : (stepOf(graph, after)?.group ?? null)
  const added = { ...graph, steps: [...graph.steps, newStep(graph, id, 'New step', inGroup)] }
  return [inGroup || !goesOn(graph, after) ? added : connect(added, after, id), id]
}

/** Steps that run at the same time, all of them done before it goes on: a group with two steps to begin with. */
export function addGroup(graph: RecipeGraph, after: string | null): [RecipeGraph, string] {
  const id = fresh(graph, 'g')
  let added: RecipeGraph = { ...graph, groups: [...graph.groups, { id, name: GROUP_NAME, wait: 'all' }] }
  added = { ...added, steps: [...added.steps, newStep(added, fresh(added, 's'), 'First at once', id)] }
  added = { ...added, steps: [...added.steps, newStep(added, fresh(added, 's'), 'Second at once', id)] }
  return [goesOn(graph, after) ? connect(added, after, id) : added, id]
}

/** A Room step (slice 84e): its roles meet in one room, never at once with other steps - after the part that is chosen. */
export function addRoom(graph: RecipeGraph, after: string | null): [RecipeGraph, string] {
  const id = fresh(graph, 's')
  const added = { ...graph, steps: [...graph.steps, { ...newStep(graph, id, 'Meeting'), who: { room: [] } }] }
  return [goesOn(graph, after) ? connect(added, after, id) : added, id]
}

export const roomOf = (who: Who | undefined): string[] | null => (who && 'room' in who ? who.room : null)

/** K-evrim: a step of candidates, as a card and a list say it: "Coder ×3 · target 80". */
export const candidatesLine = (who: Extract<Who, { candidates: string }>) => `${who.candidates} ×${who.most}${who.target != null ? ` · target ${who.target}` : ''}`

/** The roles a step's agents are of, by name - its role's, its team's stages', its room's members' - and how they work in it. */
export function stepRoles(who: Who, teams: Team[], roles: Role[]): [names: string[], as: 'step' | 'room'] {
  if ('role' in who) return [[who.role], 'step']
  if ('candidates' in who) return [[who.candidates], 'step']
  if ('room' in who) return [who.room, 'room']
  if (!('team' in who)) return [[], 'step']
  const ids = teams.find(one => one.name === who.team)?.stages.flatMap(stage => stage.roles) ?? []
  return [roles.filter(role => ids.includes(role.id)).map(role => role.name), 'step']
}

/** "Ask me, then in": an end, after the part that is chosen. */
export function addEnd(graph: RecipeGraph, after: string | null): [RecipeGraph, string] {
  const id = fresh(graph, 'end')
  const added = { ...graph, ends: [...graph.ends, { id, then: 'in' as const }] }
  return [goesOn(graph, after) ? connect(added, after, id) : added, id]
}

/** What comes before a step or group: the parts with an arrow to it (to its group, for a step in one). */
export function before(graph: RecipeGraph, id: string): string[] {
  const at = stepOf(graph, id)?.group ?? id
  return graph.arrows.filter(arrow => arrow.to === at).map(arrow => arrow.from)
}

/** A loop back from a step or group (a review) to the step before it, at most two rounds; none where nothing comes before it. */
export function loopBack(graph: RecipeGraph, from: string): RecipeGraph {
  const back = before(graph, from).find(id => kindOf(graph, id) === 'step' || kindOf(graph, id) === 'group')
  return back ? setLoop(graph, from, back, ROUNDS) : graph
}

/** The loop back from `from` (one a part): to `to` at most `rounds` times; `to` null takes it away. */
export function setLoop(graph: RecipeGraph, from: string, to: string | null, rounds?: number | null): RecipeGraph {
  const was = graph.loops.find(loop => loop.from === from)
  const others = graph.loops.filter(loop => loop.from !== from)
  return { ...graph, loops: to === null ? others : [...others, { from, to, rounds: rounds === undefined ? (was?.rounds ?? ROUNDS) : rounds }] }
}

export const loopOf = (graph: RecipeGraph, from: string) => graph.loops.find(loop => loop.from === from) ?? null

/**
 * A step changed. Put in a group or out of one, its arrows go (in a group it goes on with the group, and its branch's arrows are
 * its group's). Where it was dragged goes too (a group's step is placed from its group's corner): the board places it.
 */
export function changeStep(graph: RecipeGraph, id: string, change: Partial<RecipeStep>): RecipeGraph {
  const moved = change.group !== undefined && change.group !== stepOf(graph, id)?.group
  return {
    ...graph,
    steps: graph.steps.map(step => (step.id === id ? { ...step, ...change, ...(moved && { pos: null }) } : step)),
    arrows: moved ? graph.arrows.filter(arrow => arrow.from !== id && arrow.to !== id) : graph.arrows,
  }
}

export const renameGroup = (graph: RecipeGraph, id: string, name: string): RecipeGraph => ({
  ...graph,
  groups: graph.groups.map(group => (group.id === id ? { ...group, name } : group)),
})

/** K-tarif-kol: a group waits for all its branches, or goes on once the first is done (the others stopped). Its name, while
 * still a default, says which; one the user typed stays. */
export const waitFor = (graph: RecipeGraph, id: string, wait: RecipeGraph['groups'][number]['wait']): RecipeGraph => ({
  ...graph,
  groups: graph.groups.map(group => {
    if (group.id !== id) return group
    const name = group.name === GROUP_NAME || group.name === FIRST_NAME ? (wait === 'first' ? FIRST_NAME : GROUP_NAME) : group.name
    return { ...group, wait, name }
  }),
})

export const changeEnd = (graph: RecipeGraph, id: string, then: End['then']): RecipeGraph => ({
  ...graph,
  ends: graph.ends.map(end => (end.id === id ? { ...end, then } : end)),
})

/** A part taken off the board, with its arrows and loops; a group with its steps. */
export function remove(graph: RecipeGraph, id: string): RecipeGraph {
  if (id === START) return graph
  const gone = new Set([id, ...graph.steps.filter(step => step.group === id).map(step => step.id)])
  return {
    ...graph,
    steps: graph.steps.filter(step => !gone.has(step.id)),
    groups: graph.groups.filter(group => group.id !== id),
    ends: graph.ends.filter(end => end.id !== id),
    arrows: graph.arrows.filter(arrow => !gone.has(arrow.from) && !gone.has(arrow.to)),
    loops: graph.loops.filter(loop => !gone.has(loop.from) && !gone.has(loop.to)),
  }
}

/** What a step is handed: the work of what comes before it, and the findings of a loop back to it. */
export function gets(graph: RecipeGraph, id: string): string {
  // (A group's step after another in its branch: that one's work.)
  const inner = stepOf(graph, id)?.group ? graph.arrows.find(arrow => arrow.to === id) : undefined
  const from = inner ? [inner.from] : before(graph, id)
  const looped = graph.loops.filter(loop => loop.to === id).map(loop => nameOf(graph, loop.from))
  const first = from.length === 0 ? 'nothing yet: no arrow comes to it' : from.map(one => (one === START ? 'your message' : `the work of ${nameOf(graph, one)}`)).join(' and ')
  return looped.length ? `${first}, and the findings of ${looped.join(' and ')} when looped back` : first
}

/** One line of what the recipe does, in the order it does it: "Write the spec → Build it → 4 at once (≤2 rounds) → Ask me, then in";
 * a fork's ways side by side (B-375): "(3 at once ∥ 2 at once) → Ask me, then in". */
export function summary(graph: RecipeGraph): string {
  const word = (id: string) => {
    const loop = loopOf(graph, id)
    const who = stepOf(graph, id)?.who
    const name = kindOf(graph, id) === 'group' ? `${graph.steps.filter(step => step.group === id).length} at once` : nameOf(graph, id)
    const named = who && 'candidates' in who ? `${name} · ${candidatesLine(who)}` : name
    return loop?.rounds ? `${named} (≤${loop.rounds} rounds)` : named
  }
  // (Not a group's arrows between its own steps: its branches.)
  const outer = graph.arrows.filter(arrow => !stepOf(graph, arrow.from)?.group || stepOf(graph, arrow.from)?.group !== stepOf(graph, arrow.to)?.group)
  const outs = (id: string) => outer.filter(arrow => arrow.from === id).map(arrow => arrow.to)
  const ins = (id: string) => outer.filter(arrow => arrow.to === id).length
  const words: string[] = []
  const seen = new Set<string>()
  let at = START
  while (!seen.has(at) && outs(at).length > 0) {
    seen.add(at)
    const tos = outs(at)
    // As the runner reads a fork (`recipe_run.ways`): each way while its parts have one arrow in and one on, to where they meet.
    const ways = tos.map(one => {
      const line: string[] = []
      while (tos.length > 1 && ins(one) === 1 && outs(one).length === 1 && !line.includes(one)) {
        line.push(one)
        one = outs(one)[0]
      }
      return { line, stop: one }
    })
    if (tos.length > 1) words.push(`(${ways.filter(way => way.line.length).map(way => way.line.map(word).join(' → ')).join(' ∥ ')})`)
    at = ways[0].stop
    if (!seen.has(at)) words.push(word(at))
  }
  return words.join(' → ') || 'nothing drawn yet'
}

/** Where each part is drawn: rows by how far from the start it is, the parts of a row side by side. */
export interface Place {
  x: number
  y: number
  w: number
  h: number
}
export const STEP_W = 200
export const STEP_H = 50
const GAP = 34
const ROW = 4
const GROUP_PAD = 12
/** Where a group's branches fork, under its name (B-374). */
export const GROUP_HEAD = 30
/** Room in a group for its fork and join arrows, and for a branch's arrow between two of its steps. */
const FAN = 30
const LINK = 26

/** How far right of the parts a loop's curve and its words reach: kept in view with them. */
export const LOOP_ROOM = 200
const LOOP_OUT = 45

/**
 * A loop back drawn from the right side of the part it leaves to the right side of the one it goes back to: a curve out to
 * the right, its words just past the curve's farthest point (at its middle, a quarter of the ends and three of the bend).
 */
export function loopCurve(sx: number, sy: number, tx: number, ty: number): { path: string; labelX: number; labelY: number } {
  const bend = Math.max(sx, tx) + LOOP_OUT
  return { path: `M${sx},${sy} C${bend},${sy} ${bend},${ty} ${tx},${ty}`, labelX: (sx + tx) / 8 + (3 * bend) / 4 + 6, labelY: (sy + ty) / 2 }
}

/** K-tarif-kol: a group's branches, each its steps along their arrows from one no arrow comes to (B-374: drawn side by side). */
export function branches(graph: RecipeGraph, group: string): string[][] {
  const ids = graph.steps.filter(step => step.group === group).map(step => step.id)
  const firsts = ids.filter(id => !graph.arrows.some(arrow => arrow.to === id))
  const seen = new Set<string>()
  const lines: string[][] = []
  // (Arrows that go round with no first step, as a model may draw them: walked from where they are met.)
  for (const first of [...firsts, ...ids]) {
    if (seen.has(first)) continue
    const line: string[] = []
    for (let at: string | undefined = first; at && !seen.has(at); at = graph.arrows.find(arrow => arrow.from === at && ids.includes(arrow.to))?.to) {
      seen.add(at)
      line.push(at)
    }
    lines.push(line)
  }
  return lines
}

export type Pos = NonNullable<RecipeStep['pos']>

/** A part dragged to `pos` (a group's step: from its group's corner), kept with the recipe; null: the board places it again. */
export function place(graph: RecipeGraph, id: string, pos: Pos | null): RecipeGraph {
  const at = <T extends { id: string }>(one: T) => (one.id === id ? { ...one, pos } : one)
  return { ...graph, steps: graph.steps.map(at), groups: graph.groups.map(at), ends: graph.ends.map(at) }
}

/** "Tidy up": every part placed by the board again. */
export function tidy(graph: RecipeGraph): RecipeGraph {
  const back = <T extends { pos?: Pos | null }>(one: T) => ({ ...one, pos: null })
  return { ...graph, steps: graph.steps.map(back), groups: graph.groups.map(back), ends: graph.ends.map(back) }
}

/** Where each part is drawn: where the user dragged it, else by rows from the start (`pos` set wins; the start is the board's). */
export function layout(graph: RecipeGraph): Record<string, Place> {
  const depth: Record<string, number> = { [START]: 0 }
  const walk = (todo: string[]) => {
    while (todo.length) {
      const at = todo.shift() as string
      for (const arrow of graph.arrows.filter(one => one.from === at)) {
        if (depth[arrow.to] !== undefined || kindOf(graph, arrow.to) === null) continue
        depth[arrow.to] = depth[at] + 1
        todo.push(arrow.to)
      }
    }
  }
  walk([START])
  // What no arrow from the start reaches yet is drawn below it, from its own first parts along its arrows, to be joined
  // (B-108: ten steps in one row ran off the board).
  const tops = [...graph.steps.filter(step => !step.group).map(step => step.id), ...graph.groups.map(group => group.id), ...graph.ends.map(end => end.id)]
  const loose = tops.filter(id => depth[id] === undefined)
  // (An end nothing leads to is no first part: it stays at the bottom.)
  const firsts = loose.filter(id => kindOf(graph, id) !== 'end' && !graph.arrows.some(arrow => arrow.to === id && loose.includes(arrow.from)))
  const below = Math.max(0, ...Object.values(depth)) + 1
  for (const id of firsts) depth[id] = below
  walk(firsts)
  // (Arrows that go round with no first part, as a model may draw them, and ends not joined yet: in a row at the bottom.)
  const last = Math.max(0, ...Object.values(depth)) + 1
  const rows: string[][] = []
  for (const id of [START, ...tops]) (rows[depth[id] ?? last] ??= []).push(id)
  // shortcut: a group's branches all in one row, so one of many makes the board zoom out (four: 0.77 in a 1024 px window); wrap
  // its columns if a wide group is too small to read.
  const inGroups = Object.fromEntries(graph.groups.map(group => [group.id, branches(graph, group.id)]))
  const size = (id: string) => {
    const kind = kindOf(graph, id)
    if (kind === 'group') {
      const [across, down] = [Math.max(1, inGroups[id].length), Math.max(1, ...inGroups[id].map(line => line.length))]
      return { w: across * STEP_W + (across - 1) * GAP + 2 * GROUP_PAD, h: GROUP_HEAD + 2 * FAN + down * STEP_H + (down - 1) * LINK }
    }
    return kind === 'step' ? { w: STEP_W, h: STEP_H } : { w: 160, h: 40 }
  }
  const places: Record<string, Place> = {}
  let y = 0
  // A row of more than ROW parts not joined yet goes on under itself: the drawing stays narrow enough to be seen whole. (A row
  // the start leads to stays one: its parts run side by side.)
  const lines = rows.flatMap((row, at) => (at < below ? [row] : Array.from({ length: Math.ceil(row.length / ROW) }, (_, n) => row.slice(n * ROW, (n + 1) * ROW))))
  for (const row of lines) {
    const sizes = row.map(size)
    const width = sizes.reduce((sum, one) => sum + one.w, 0) + GAP * (row.length - 1)
    let x = -width / 2
    row.forEach((id, at) => {
      places[id] = { x, y, ...sizes[at] }
      x += sizes[at].w + GAP
    })
    y += Math.max(...sizes.map(one => one.h)) + 28
  }
  // A group's branches side by side in it, each one's steps one under another (where React Flow draws a child: from its group's corner).
  for (const group of graph.groups)
    inGroups[group.id].forEach((line, across) =>
      line.forEach((id, down) => (places[id] = { x: GROUP_PAD + across * (STEP_W + GAP), y: GROUP_HEAD + FAN + down * (STEP_H + LINK), w: STEP_W, h: STEP_H })),
    )
  // (A step of a group that is not drawn has no place: it is not on the board.)
  // shortcut: a group keeps the size the board gives it, so its steps move only a little inside it; size a group by its steps'
  // places if people want to arrange inside one.
  for (const one of [...graph.steps, ...graph.groups, ...graph.ends]) if (one.pos && places[one.id]) places[one.id] = { ...places[one.id], ...one.pos }
  return places
}
