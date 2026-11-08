import {
  Background,
  BackgroundVariant,
  BaseEdge,
  type Edge,
  EdgeLabelRenderer,
  type EdgeProps,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStore,
  useUpdateNodeInternals,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useRef, useState } from 'react'
import { ApiError, errorText } from '../api/client'
import type { CandidateModel, Provider, Recipe, RecipeDraft, RecipeGraph, RecipeStep, Recipes, Role, RoleModel, Team } from '../api/types'
import { type LoadModels, ModelNameInput } from '../models/ModelNameInput'
import {
  type End,
  END_NAMES,
  GROUP_HEAD,
  LOOP_ROOM,
  START,
  type Who,
  addEnd,
  addGroup,
  addRoom,
  addStep,
  before,
  branches,
  candidatesLine,
  changeEnd,
  changeStep,
  connect,
  disconnect,
  emptyGraph,
  gets,
  goesOn,
  kindOf,
  layout,
  loopBack,
  loopCurve,
  loopOf,
  loopTargets,
  nameOf,
  place,
  remove,
  renameGroup,
  roomOf,
  setLoop,
  stepRoles,
  summary,
  targets,
  tidy,
  waitFor,
} from './recipeGraph'
import { cannotOf } from './chart'
import { Cannot } from './roleParts'

/** What reads, saves and drafts a recipe (the store's methods, by their names). Each throws ApiError. */
export interface RecipeActions {
  /** KOLONİ's recipes, the ready ones first, and with a folder its own `.koloni/recipes/`. */
  recipes: (projectId: string | null) => Promise<Recipes>
  /** A recipe changed where it is kept; a new one (null) in KOLONİ, or in the folder of `projectId`. */
  saveRecipe: (recipe: Recipe | null, body: { name: string; graph: RecipeGraph }, projectId: string | null) => Promise<Recipe>
  deleteRecipe: (recipe: Recipe) => Promise<void>
  /** The Lead's model asked once to draw a sentence as a recipe: nothing is saved. */
  draftRecipe: (text: string) => Promise<RecipeDraft>
}

/** The recipe the board holds: a copy of one saved (`from`), or a new one not saved yet (`from` null). */
interface Draft {
  name: string
  graph: RecipeGraph
  from: Recipe | null
}

const recipeKey = (recipe: Recipe) => (recipe.project_id ? `folder:${recipe.file}` : recipe.id)
const opened = (recipe: Recipe): Draft => ({ name: recipe.name, graph: recipe.graph, from: recipe })

const whoValue = (who: Who) =>
  'experts' in who ? `experts:${who.experts}` : 'lead' in who ? 'lead' : 'role' in who ? `role:${who.role}` : 'candidates' in who ? `candidates:${who.candidates}` : 'team' in who ? `team:${who.team}` : 'room'
const whoOf = (value: string): Who =>
  value === 'lead'
    ? { lead: true }
    : value.startsWith('experts:')
      ? { experts: value.slice(8) as Extract<Who, { experts: unknown }>['experts'] }
      : value.startsWith('role:')
        ? { role: value.slice(5) }
        : value.startsWith('candidates:')
          ? { candidates: value.slice(11), most: 2, models: 'auto' }
          : { team: value.slice(5) }
const stagesOf = (team: Team | undefined) => team?.stages.map(stage => stage.name).join(', then ') ?? 'no such team here'
/** A step's chip and the line under its name: who does it. */
const whoLine = (who: Who, teams: Team[]): [string, string] =>
  'experts' in who
    ? ['experts', who.experts === 'stale' ? 'the team’s experts whose guide is old: they learn' : who.experts === 'learned' ? 'the team’s experts that have learned, at once' : 'the team’s experts, at once']
    : 'room' in who
    ? ['Room', who.room.join(' · ') || 'no roles yet']
    : 'lead' in who
      ? ['Orchestrator picks', 'the Orchestrator picks who']
      : 'role' in who
        ? ['role', who.most ? `${who.role}, up to ${who.most}` : who.role]
        : 'candidates' in who
          ? ['Candidates', candidatesLine(who)]
          : ['team stages', `${who.team} → ${stagesOf(teams.find(team => team.name === who.team))}`]

interface NodeData extends Record<string, unknown> {
  kind: 'start' | 'step' | 'group' | 'end'
  title: string
  chip?: string
  sub?: string
  problem?: string
  /** What keeps it from running, or stands in its agents' way where they run now (B-89): shown as ⚠ on it (B-108). */
  warn?: string
  /** A step of a group: its arrows only join its group's steps into branches (K-tarif-kol); its group's go in and out. */
  inGroup: boolean
  chosen: boolean
  onPick: () => void
}

/** A part of the drawing: its name, who does it, and what the server said keeps it from running. One button to choose it. */
function RecipeNode({ id, data, width, height }: NodeProps<Node<NodeData>>) {
  const { kind, inGroup } = data
  // Its handles read again as it goes in or out of a group, or a group widens with a branch: given as measured, its size alone
  // would not have them read (B-85).
  const handlesChanged = useUpdateNodeInternals()
  useEffect(() => handlesChanged(id), [handlesChanged, id, inGroup, width, height])
  return (
    <div className={`recipe-node recipe-${kind}${data.chosen ? ' recipe-node-chosen' : ''}${data.problem ? ' recipe-node-problem' : ''}${data.warn ? ' recipe-node-warned' : ''}`}>
      {/* An arrow is drawn from where it leaves only (B-85: one drawn from the right side's target went the wrong way); the
          loop's source over its target there, to be taken. */}
      {kind !== 'start' && <Handle type="target" position={Position.Top} id="in" isConnectableStart={false} />}
      {kind !== 'end' && <Handle type="source" position={Position.Bottom} id="out" />}
      {/* B-374: where its branches fork, under its name, and join, at its way out; the board's own, never dragged from. */}
      {kind === 'group' && (
        <>
          <Handle type="source" position={Position.Bottom} id="fork" className="recipe-branch-handle" isConnectable={false} style={{ top: GROUP_HEAD, bottom: 'auto' }} />
          <Handle type="target" position={Position.Top} id="join" className="recipe-branch-handle" isConnectable={false} style={{ top: 'auto', bottom: 0 }} />
        </>
      )}
      {(kind === 'step' || kind === 'group') && (
        <>
          <Handle type="target" position={Position.Right} id="loop-in" className="recipe-loop-handle" isConnectableStart={false} />
          <Handle type="source" position={Position.Right} id="loop-out" className="recipe-loop-handle" />
        </>
      )}
      <button type="button" className="recipe-node-open" aria-pressed={data.chosen} onClick={data.onPick}>
        <span className="recipe-node-name">
          {data.title}
          {data.chip && <span className="recipe-chip">{data.chip}</span>}
        </span>
        {data.sub && <span className="recipe-node-sub">{data.sub}</span>}
      </button>
      {data.warn && (
        <span className="recipe-node-warn" role="img" aria-label={data.warn} title={data.warn}>
          ⚠
        </span>
      )}
    </div>
  )
}

/** A loop back, dashed red: out of the right side of the part it leaves, its arrow on the right side of the one it goes back to. */
function LoopEdge({ sourceX, sourceY, targetX, targetY, markerEnd, label }: EdgeProps) {
  const { path, labelX, labelY } = loopCurve(sourceX, sourceY, targetX, targetY)
  return (
    <>
      <BaseEdge path={path} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        <span className="recipe-loop-label" style={{ transform: `translate(${labelX}px, ${labelY}px) translateY(-50%)` }}>
          {label}
        </span>
      </EdgeLabelRenderer>
    </>
  )
}

const NODE_TYPES = { recipe: RecipeNode }
const EDGE_TYPES = { loop: LoopEdge }
const PAD = 16
// (Under React Flow's 0.5: ten steps one under another fit a board tidied up, B-108.)
const MIN_ZOOM = 0.25

interface BoardProps {
  draft: Draft
  roles: Role[]
  teams: Team[]
  models?: Record<string, RoleModel>
  chosen: string | null
  problems: Record<string, string[]>
  readOnly: boolean
  onChoose: (id: string | null) => void
  onChange: (graph: RecipeGraph) => void
}

/** The drawing on a board of its own (not the live canvas): parts where the user dragged them, else laid out by themselves, arrows down, loops back in red. */
function Board({ draft, roles, teams, models, chosen, problems, readOnly, onChoose, onChange }: BoardProps) {
  const { graph } = draft
  const flow = useReactFlow()
  const places = layout(graph)
  // (A group comes before its steps: React Flow draws a child inside a parent it already has.)
  const order = [START, ...graph.steps.filter(step => !step.group).map(step => step.id), ...graph.groups.map(group => group.id), ...graph.ends.map(end => end.id)]
  const width = useStore(state => state.width)
  const height = useStore(state => state.height)
  const left = Math.min(...order.map(id => places[id].x))
  const right = Math.max(...order.map(id => places[id].x + places[id].w)) + (graph.loops.length ? LOOP_ROOM : 0)
  const top = Math.min(...order.map(id => places[id].y))
  const bottom = Math.max(...order.map(id => places[id].y + places[id].h))
  // (Its own fit, not React Flow's: that one leaves out a loop's words right of the parts, cut off by a group's wide branches.)
  const zoom = Math.max(MIN_ZOOM, Math.min(1, (width - 2 * PAD) / (right - left), (height - 2 * PAD) / (bottom - top)))
  // The parts, the arrows that lay them out and the board's size: the view is set again only as one of them changes - never
  // under a part being dragged, nor for the size alone once a part was (a refused save's alert above the board, gone at the
  // next Save, re-centred a drawing dragged aside).
  // shortcut: after a drag a board made smaller (the window) does not fit the drawing again till a part is added or Tidy up;
  // refit on a size that cuts parts off if that is missed.
  const shape = `${order.join(' ')} ${graph.arrows.map(arrow => `${arrow.from}>${arrow.to}`).join(' ')} ${graph.loops.length}`
  const size = `${width}x${height}`
  const placed = useRef<[string, string] | null>(null)
  const dragged = useRef(false)
  useEffect(() => {
    // All of it in view (B-85): at the canvas's size of words, in the middle and from the top, where it fits; else smaller.
    // shortcut: a drawing too big at the board's least zoom (MIN_ZOOM) is cut; pan it (the wheel), or a fit button if that is ever wanted.
    if (!width || !height) return
    const [was, wasSize] = placed.current ?? []
    if (was === shape && (wasSize === size || dragged.current)) return
    if (was !== shape) dragged.current = false
    placed.current = [shape, size]
    void flow.setViewport({ x: (width - (left + right) * zoom) / 2, y: PAD - top * zoom, zoom })
  }, [zoom, left, right, top, width, height, flow, shape, size])
  // (A loop only back to a part on the way there, as the panel offers: one dropped further down is no loop.)
  const join = (from: string, to: string, handle: string | null) =>
    handle !== 'loop-out' ? connect(graph, from, to) : loopTargets(graph, from).includes(to) ? setLoop(graph, from, to) : graph
  const data = (id: string): NodeData => {
    const kind = kindOf(graph, id) ?? 'step'
    const step = graph.steps.find(one => one.id === id)
    const [chip, sub] = step ? whoLine(step.who, teams) : [undefined, undefined]
    return {
      kind,
      title: nameOf(graph, id),
      chip,
      sub: step ? `${sub}${step.ask_me ? ' · ask me to approve it' : ''}${step.when ? ' · only if the step before found a problem' : ''}` : sub,
      problem: problems[id]?.join(' · '),
      warn: [...(step ? stepCannot(step.who, teams, roles, models) : []), ...(problems[id] ?? [])].join(' · ') || undefined,
      inGroup: !!step?.group,
      chosen: chosen === id,
      onPick: () => onChoose(id),
    }
  }
  // Each dragged where the user wants it (the start stays where the board puts it): a group with its steps, a group's step inside it.
  // (Given as measured too: a node made anew each render without it has its handles read again, and its arrows are not drawn
  // meanwhile - after a save, at times, never again till the recipe was reopened, B-85.)
  const sized = (id: string) => ({ position: places[id], width: places[id].w, height: places[id].h, measured: { width: places[id].w, height: places[id].h } })
  const nodes: Node<NodeData>[] = [
    ...order.map(id => ({ id, ...sized(id) })),
    ...graph.steps.filter(step => step.group && places[step.group]).map(step => ({ id: step.id, parentId: step.group as string, extent: 'parent' as const, ...sized(step.id) })),
  ].map(node => ({ ...node, type: 'recipe', data: data(node.id), draggable: !readOnly && node.id !== START, selectable: false }))
  const edges: Edge[] = [
    // (By place in the list: two arrows alike, which the server refuses, are still two edges.)
    ...graph.arrows.map((arrow, at) => ({
      id: `a${at}`,
      source: arrow.from,
      target: arrow.to,
      sourceHandle: 'out',
      targetHandle: 'in',
      markerEnd: { type: MarkerType.ArrowClosed },
      // (A group that goes on once its first branch is done says so on its way out.)
      ...(graph.groups.some(group => group.id === arrow.from && group.wait === 'first') && { label: 'first done', labelStyle: { fill: 'var(--text)', fontSize: 'var(--text-meta)' } }),
    })),
    // B-374: a group's branches fork from under its name and join at its way out, so they read as running side by side.
    ...graph.groups.flatMap(group =>
      branches(graph, group.id).flatMap(line => [
        { id: `fork-${line[0]}`, source: group.id, target: line[0], sourceHandle: 'fork', targetHandle: 'in', markerEnd: { type: MarkerType.ArrowClosed } },
        { id: `join-${line[line.length - 1]}`, source: line[line.length - 1], target: group.id, sourceHandle: 'out', targetHandle: 'join', markerEnd: { type: MarkerType.ArrowClosed } },
      ]),
    ),
    ...graph.loops.map((loop, at) => ({
      id: `l${at}`,
      source: loop.from,
      target: loop.to,
      sourceHandle: 'loop-out',
      targetHandle: 'loop-in',
      type: 'loop',
      className: 'recipe-loop',
      // (Over the group it leaves from: not hidden by the group's steps.)
      zIndex: 5,
      label: loop.rounds ? `back, at most ${loop.rounds} round${loop.rounds === 1 ? '' : 's'}` : 'back, no round limit',
      markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--warn)' },
    })),
  ]
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      panOnScroll
      minZoom={MIN_ZOOM}
      nodesConnectable={!readOnly}
      nodesFocusable={false}
      edgesFocusable={false}
      deleteKeyCode={null}
      // A part dragged: where it is now, kept in the drawing (saved with it), in whole pixels.
      onNodesChange={changes => {
        const moved = changes.reduce((now, one) => (one.type === 'position' && one.position ? place(now, one.id, { x: Math.round(one.position.x), y: Math.round(one.position.y) }) : now), graph)
        if (moved === graph) return
        dragged.current = true
        onChange(moved)
      }}
      // A handle dragged to another part: an arrow, or from the right side a loop back.
      onConnect={({ source, target, sourceHandle }) => onChange(join(source, target, sourceHandle))}
      // Let go anywhere on a part, not only on its handle: the arrow goes to that part (B-85: a drag missed the handle and drew nothing).
      onConnectEnd={(event, state) => {
        if (state.isValid || !state.fromNode || state.fromHandle?.type !== 'source') return
        const at = 'changedTouches' in event ? event.changedTouches[0] : event
        const to = document.elementFromPoint(at.clientX, at.clientY)?.closest('.react-flow__node')?.getAttribute('data-id')
        if (to && to !== state.fromNode.id) onChange(join(state.fromNode.id, to, state.fromHandle.id ?? null))
      }}
      // (A node React Flow sees no click on takes no pointer at all: its button would be under the pane.)
      onNodeClick={(_, node) => onChoose(node.id)}
      onEdgeClick={(_, edge) => onChoose(edge.source)}
      onPaneClick={() => onChoose(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={16} color="var(--canvas-dot)" />
    </ReactFlow>
  )
}

interface PanelProps {
  graph: RecipeGraph
  id: string
  roles: Role[]
  teams: Team[]
  problems: string[]
  readOnly: boolean
  onChange: (graph: RecipeGraph) => void
  onChoose: (id: string | null) => void
  models?: Record<string, RoleModel>
  providers?: Provider[]
  onModels?: LoadModels
}

/** What stands in the way of a step's agents where their roles run now (B-89): a role's, a team's stages', a room's members'. */
function stepCannot(who: Who, teams: Team[], roles: Role[], models?: Record<string, RoleModel>): string[] {
  const [names, as] = stepRoles(who, teams, roles)
  return names.flatMap(name => cannotOf(models?.[name], as).map(line => `${name}: ${line}`))
}

/** The chosen part: who does it, what it gets, when it is done, what happens when it fails, where it goes on and loops back. */
function PartPanel({ graph, id, roles, teams, problems, readOnly, onChange, onChoose, models, providers = [], onModels }: PanelProps) {
  const kind = kindOf(graph, id)
  const step = graph.steps.find(one => one.id === id)
  const group = graph.groups.find(one => one.id === id)
  const end = graph.ends.find(one => one.id === id)
  const name = nameOf(graph, id)
  const change = (part: Partial<RecipeStep>) => onChange(changeStep(graph, id, part))
  const loop = loopOf(graph, id)
  const nexts = graph.arrows.filter(arrow => arrow.from === id).map(arrow => arrow.to)
  const at = graph.steps.indexOf(step as RecipeStep)
  // A Who that names what is not here is kept on show: the server says so as it is saved.
  const who = step ? whoValue(step.who) : 'lead'
  const known =
    who === 'lead' || who.startsWith('experts:') || roles.some(role => `role:${role.name}` === who || `candidates:${role.name}` === who) || teams.some(team => `team:${team.name}` === who)
  const room = roomOf(step?.who)
  const one = step && 'role' in step.who ? step.who : null
  const candidates = step && 'candidates' in step.who ? step.who : null
  // K-evrim-model: the user's model for each candidate, from the providers agents may use.
  const picks = candidates && Array.isArray(candidates.models) ? candidates.models : null
  const guided = providers.filter(p => p.for_agents && p.enabled !== false)
  // B-388: one whose agent of this role works in the project itself (`step` false, as the spawn refuses it) cannot be a candidate.
  const runOn = candidates ? models?.[candidates.candidates]?.run_on : undefined
  const inCopy = (id: string) => runOn?.find(r => r.provider_id === id)?.step !== false
  const setPick = (at: number, pick: CandidateModel) => candidates && picks && change({ who: { ...candidates, models: picks.map((one, i) => (i === at ? pick : one)) } })
  return (
    <aside className="role-panel recipe-panel" aria-label={`Recipe part ${name}`}>
      <h3>{name}</h3>
      <div className="muted">
        {kind === 'step'
          ? `Step ${at + 1} of ${graph.steps.length}`
          : group?.wait === 'first'
            ? 'Steps at the same time; it goes on once one branch is done - the others are stopped; what they already changed stays in the work. A branch that fails is out while another can still be done; if all fail, the last one’s “If it fails” holds'
            : kind === 'group'
              ? 'Steps at the same time, all done before it goes on'
              : kind === 'start'
                ? 'Where the recipe begins: the message you send'
                : 'Where the recipe ends'}
      </div>
      {problems.length > 0 && (
        <ul role="alert" className="alert recipe-said">
          {problems.map(said => (
            <li key={said}>{said}</li>
          ))}
        </ul>
      )}
      <fieldset className="recipe-rows" disabled={readOnly}>
        {(step || group) && (
          <label className="recipe-row">
            <span className="muted">Name</span>
            <input className="input" value={name} maxLength={60} onChange={e => onChange(step ? changeStep(graph, id, { name: e.target.value }) : renameGroup(graph, id, e.target.value))} />
          </label>
        )}
        {group && (
          // K-tarif-kol: its branches - its steps joined by arrows inside it - all, or the first one done.
          <label className="recipe-row">
            <span className="muted">Wait for</span>
            <select className="input" aria-label="Wait for" value={group.wait ?? 'all'} onChange={e => onChange(waitFor(graph, id, e.target.value as typeof group.wait))}>
              <option value="all">all branches</option>
              <option value="first">the first one done</option>
            </select>
          </label>
        )}
        {step && (
          <>
            {room ? (
              // A Room step (slice 84e): 2 to 6 roles that meet in one room; one named that is not here is kept on show.
              <div className="recipe-row" role="group" aria-label="Who meets in the room">
                <span className="muted">Who</span>
                <div className="recipe-nexts">
                  {[...new Set([...roles.map(role => role.name), ...room])].map(name => (
                    <label key={name} className="choice">
                      <input type="checkbox" checked={room.includes(name)} onChange={e => change({ who: { room: e.target.checked ? [...room, name] : room.filter(one => one !== name) } })} />
                      <span>{roles.some(role => role.name === name) ? name : `${name} (not here)`}</span>
                    </label>
                  ))}
                  <span className="muted">2 to 6 roles, in one room.</span>
                </div>
              </div>
            ) : (
            <label className="recipe-row">
              <span className="muted">Who</span>
              <select className="input" value={who} onChange={e => change({ who: whoOf(e.target.value) })}>
                <option value="lead">The Orchestrator picks</option>
                <optgroup label="The team’s experts">
                  <option value="experts:all">All of them, at once</option>
                  <option value="experts:stale">Those whose guide is old (they learn)</option>
                  <option value="experts:learned">Those that have learned (none: skipped)</option>
                </optgroup>
                {!known && <option value={who}>{who.slice(who.indexOf(':') + 1)} (not here)</option>}
                <optgroup label="A role">
                  {roles.map(role => (
                    <option key={role.id} value={`role:${role.name}`}>
                      {role.name}
                    </option>
                  ))}
                </optgroup>
                {/* K-evrim: each does the whole step its own way, in a copy of its own; the measure command scores them. */}
                <optgroup label="Candidates (the best one goes on)">
                  {roles.map(role => (
                    <option key={role.id} value={`candidates:${role.name}`}>
                      Candidates: {role.name}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="A team’s stages">
                  {teams.map(team => (
                    <option key={team.id} value={`team:${team.name}`}>
                      {team.name}: {stagesOf(team)}
                    </option>
                  ))}
                </optgroup>
              </select>
            </label>
            )}
            {one && (
              // K-rol-cogul: up to this many of its role, as many as the Lead splits the work into. (Named apart from a
              // loop's "At most" rounds, which this panel may show too.)
              <label className="recipe-row">
                <span className="muted">At most</span>
                <select
                  className="input"
                  aria-label="At most of its role"
                  value={one.most ?? 1}
                  onChange={e => {
                    const most = Number(e.target.value)
                    change({ who: most > 1 ? { role: one.role, most } : { role: one.role } })
                  }}
                >
                  {[1, 2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>
                      {n} agent{n === 1 ? '' : 's'}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {candidates && (
              <label className="recipe-row">
                <span className="muted">At most</span>
                <select
                  className="input"
                  aria-label="At most candidates"
                  value={candidates.most}
                  onChange={e => {
                    const most = Number(e.target.value)
                    // (Your list holds one model a candidate at most: one past it is cut, or the save is refused.)
                    change({ who: { ...candidates, most, models: Array.isArray(candidates.models) ? candidates.models.slice(0, most) : candidates.models } })
                  }}
                >
                  {[2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>
                      {n} candidates
                    </option>
                  ))}
                </select>
              </label>
            )}
            {candidates && (
              // K-evrim: rounds (its loop to itself) stop once the picked one scores this much; empty: every round runs.
              <label className="recipe-row">
                <span className="muted">Target</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  aria-label="Target score"
                  placeholder="none: every round runs"
                  value={candidates.target ?? ''}
                  onChange={e => change({ who: { ...candidates, target: e.target.value === '' ? null : Math.min(100, Math.max(0, Math.round(Number(e.target.value)))) } })}
                />
              </label>
            )}
            {candidates && (
              // K-evrim-model: whose the candidates' models are - the Lead's to pick (as nothing is said, "auto" is left out of the file), the role's, or yours.
              <label className="recipe-row">
                <span className="muted">Models</span>
                <select
                  className="input"
                  aria-label="Models"
                  value={Array.isArray(candidates.models) ? 'each' : (candidates.models ?? 'auto')}
                  onChange={e => {
                    const how = e.target.value
                    change({ who: { ...candidates, models: how === 'each' ? [{ provider_id: (guided.find(p => inCopy(p.id)) ?? guided[0])?.id ?? '', model_id: null }] : (how as 'auto' | 'same') } })
                  }}
                >
                  <option value="auto">Auto, the Lead picks</option>
                  <option value="same">Same model</option>
                  <option value="each" disabled={guided.length === 0 && !picks}>
                    I pick each
                  </option>
                </select>
              </label>
            )}
            {candidates && picks && (
              <div className="recipe-row" role="group" aria-label="Each candidate’s model">
                <span className="muted">Each</span>
                <div className="recipe-nexts">
                  {picks.map((pick, at) => (
                    <span key={at} className="role-tier-range">
                      <select
                        className="input"
                        aria-label={`Candidate ${at + 1}’s provider`}
                        value={pick.provider_id}
                        onChange={e => setPick(at, { provider_id: e.target.value, model_id: null })}
                      >
                        {!guided.some(p => p.id === pick.provider_id) && <option value={pick.provider_id}>not one agents may use</option>}
                        {guided.map(p => (
                          <option key={p.id} value={p.id} disabled={!inCopy(p.id)}>
                            {inCopy(p.id) ? p.name : `${p.name} (can’t run in a recipe’s copy)`}
                          </option>
                        ))}
                      </select>
                      <ModelNameInput
                        label={`Candidate ${at + 1}’s model`}
                        value={pick.model_id ?? ''}
                        placeholder={guided.find(p => p.id === pick.provider_id)?.default_model ?? 'The provider’s default'}
                        providerId={pick.provider_id}
                        loadModels={onModels}
                        quiet
                        onChange={value => setPick(at, { ...pick, model_id: value.trim() || null })}
                      />
                      {picks.length > 1 && (
                        <button type="button" className="btn btn-small" aria-label={`Remove candidate ${at + 1}’s model`} onClick={() => change({ who: { ...candidates, models: picks.filter((_, i) => i !== at) } })}>
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                  {picks.length < candidates.most && (
                    <button type="button" className="btn btn-small" onClick={() => change({ who: { ...candidates, models: [...picks, picks[picks.length - 1]] } })}>
                      + Candidate {picks.length + 1}
                    </button>
                  )}
                  <span className="muted">Candidate 1 runs on the first, and so on; any past these on the role’s model.</span>
                </div>
              </div>
            )}
            <Cannot said={stepCannot(step.who, teams, roles, models)} />
            <div className="recipe-row">
              <span className="muted">Gets</span>
              <span>{gets(graph, id)}</span>
            </div>
            <label className="recipe-row">
              <span className="muted">Done when</span>
              <select className="input" value={step.done_when} onChange={e => change({ done_when: e.target.value as RecipeStep['done_when'] })}>
                <option value="done">{room ? 'the room ends: all say done, or its time or budget is up' : 'its agents say done'}</option>
                <option value="no_findings">no finding is left (a review)</option>
              </select>
            </label>
            <label className="recipe-row">
              <span className="muted">If it fails</span>
              <select className="input" value={step.if_fails} onChange={e => change({ if_fails: e.target.value as RecipeStep['if_fails'] })}>
                <option value="ask">ask me</option>
                <option value="stop">stop</option>
              </select>
            </label>
            <label className="choice recipe-row-wide">
              <input type="checkbox" checked={step.ask_me} onChange={e => change({ ask_me: e.target.checked })} />
              <span>Ask me to approve its work before it goes on</span>
            </label>
            <label className="choice recipe-row-wide">
              <input type="checkbox" checked={!!step.when} onChange={e => change({ when: e.target.checked ? 'problem' : null })} />
              <span>Only if the step before found a problem</span>
            </label>
            {/* (A room meets on its own, never at once with other steps.) */}
            {!room && (
              <label className="recipe-row">
                <span className="muted">At once</span>
                <select className="input" aria-label="At the same time as" value={step.group ?? ''} onChange={e => change({ group: e.target.value || null })}>
                  <option value="">no: on its own</option>
                  {graph.groups.map(one => (
                    <option key={one.id} value={one.id}>
                      in “{one.name}”
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="recipe-row">
              <span className="muted">Tiers</span>
              <span className="muted">as each role’s rule (the Orchestrator picks within it)</span>
            </div>
          </>
        )}
        {end && (
          <label className="recipe-row">
            <span className="muted">Then</span>
            <select className="input" aria-label="How it ends" value={end.then} onChange={e => onChange(changeEnd(graph, id, e.target.value as End['then']))}>
              {Object.entries(END_NAMES).map(([then, words]) => (
                <option key={then} value={then}>
                  {words}
                </option>
              ))}
            </select>
          </label>
        )}
        {goesOn(graph, id) && (
          <div className="recipe-row">
            <span className="muted">Goes on to</span>
            <div className="recipe-nexts">
              {nexts.map(next => (
                <span key={next} className="recipe-next">
                  {nameOf(graph, next)}
                  <button type="button" className="link-btn" aria-label={`No arrow to ${nameOf(graph, next)}`} onClick={() => onChange(disconnect(graph, id, next))}>
                    remove
                  </button>
                </span>
              ))}
              <select className="input" aria-label="Add an arrow to" value="" onChange={e => e.target.value && onChange(connect(graph, id, e.target.value))}>
                <option value="">+ an arrow to…</option>
                {targets(graph, id).map(next => (
                  <option key={next} value={next}>
                    {nameOf(graph, next)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
        {(step || group) && (
          <div className="recipe-row">
            <span className="muted">Loops back</span>
            <div className="recipe-nexts">
              <select className="input" aria-label="Loops back to" value={loop?.to ?? ''} onChange={e => onChange(setLoop(graph, id, e.target.value || null))}>
                <option value="">no loop</option>
                {/* Back to a part on the way here; one drawn otherwise (a model's draft) is kept on show, the server says why. */}
                {[...new Set([...loopTargets(graph, id), ...(loop ? [loop.to] : [])])].map(back => (
                  <option key={back} value={back}>
                    {back === id ? 'round again, from the picked one’s work' : `to ${nameOf(graph, back)}, with the findings`}
                  </option>
                ))}
              </select>
              {loop && (
                <select className="input" aria-label="At most" value={loop.rounds ?? ''} onChange={e => onChange(setLoop(graph, id, loop.to, e.target.value ? Number(e.target.value) : null))}>
                  {!loop.rounds && <option value="">no round limit</option>}
                  {[1, 2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>
                      at most {n} round{n === 1 ? '' : 's'}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        )}
      </fieldset>
      {kind !== 'start' && !readOnly && (
        <button
          type="button"
          className="btn btn-small btn-danger"
          onClick={() => {
            onChange(remove(graph, id))
            onChoose(null)
          }}
        >
          Remove {kind === 'group' ? 'the group and its steps' : 'it'}
        </button>
      )}
    </aside>
  )
}

interface Props {
  /** What a step may name: the roles (not the Lead's, not a team's lead's) and the teams. */
  roles: Role[]
  teams: Team[]
  /** The recipes as last read, or why they could not be. */
  list: Recipes | string | null
  /** The folder open now: a new recipe may be kept in its `.koloni/recipes/`. */
  projectId: string | null
  actions?: RecipeActions
  /** Read the recipes again, after one is saved or deleted. */
  reload: () => void
  /** Who uses what, by role name: what stands in a step's way is said on it. */
  models?: Record<string, RoleModel>
  /** The providers, and their models as suggested: a candidates step's "I pick each" (K-evrim-model). */
  providers?: Provider[]
  onModels?: LoadModels
}

/**
 * The Recipes tab (slice 84a): the recipes on the left, ready ones and yours, and "Or write it"; the chosen one drawn in the middle;
 * the chosen part of it on the right. Saved only when the server finds it can run; a ready one is copied to be changed.
 * shortcut: choosing another recipe drops what was changed and not saved, unasked; ask first if work is lost that way.
 */
export function RecipesTab({ roles, teams, list, projectId, actions, reload, models, providers, onModels }: Props) {
  const recipes = list && typeof list !== 'string' ? list.recipes : []
  const [picked, setChosen] = useState<string | null>(null)
  const [held, setDraft] = useState<Draft | null>(null)
  const [part, setPart] = useState<string | null>(null)
  const [inFolder, setInFolder] = useState(false)
  const [problems, setProblems] = useState<Record<string, string[]>>({})
  const [error, setError] = useState<string | null>(null)
  const [said, setSaid] = useState<string | null>(null)
  const [sentence, setSentence] = useState('')
  const [writing, setWriting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // Each recipe opened on a board of its own, seen from its top.
  const [opens, setOpens] = useState(0)
  // The first recipe on the board until one is chosen.
  const first = recipes[0]
  const draft = held ?? (first ? opened(first) : null)
  const chosen = held ? picked : first ? recipeKey(first) : null

  /** `anew`: another recipe, seen from its top; the one saved stays where it is in view. */
  const open = (next: Draft, key: string | null, saying: string | null = null, anew = true) => {
    setDraft(next)
    setChosen(key)
    setPart(null)
    setProblems({})
    setError(null)
    setSaid(saying)
    setDeleting(false)
    if (anew) setOpens(n => n + 1)
  }
  const readOnly = !!draft?.from?.ready
  const change = (graph: RecipeGraph) => {
    if (!draft) return
    setDraft({ ...draft, graph })
    // B-196: what the server said of the part being changed was of it before: it goes, and "It cannot run yet" with the last of them.
    if (part && problems[part]) {
      const left = Object.fromEntries(Object.entries(problems).filter(([at]) => at !== part))
      setProblems(left)
      if (Object.keys(left).length === 0) setError(said => (said?.startsWith('It cannot run yet') ? null : said))
    }
  }
  const add = (made: [RecipeGraph, string]) => {
    change(made[0])
    setPart(made[1])
  }
  const save = async () => {
    if (!draft || !actions) return
    setProblems({})
    setError(null)
    setSaid(null)
    try {
      const saved = await actions.saveRecipe(draft.from, { name: draft.name, graph: draft.graph }, inFolder && projectId ? projectId : null)
      reload()
      open(opened(saved), recipeKey(saved), saved.project_id && !draft.from ? 'Saved in .koloni/ in this folder (kept in git).' : 'Saved.', false)
    } catch (err) {
      // The server says what keeps it from running, at the part it is about: shown there. What the request's own check refused (an
      // empty name, B-108) is said in its words too - not as "graph.steps.0.name: Value error, …".
      const said = err instanceof ApiError && Array.isArray(err.raw) ? (err.raw as { at?: string | null; msg?: string; loc?: unknown[] }[]) : []
      const plain = (msg: unknown) => {
        const words = String(msg ?? '').replace(/^Value error, /, '')
        return words.charAt(0).toUpperCase() + words.slice(1)
      }
      const raw = said.map(one => {
        const [body, graph, list, index, field] = one.loc ?? []
        if (body === 'body' && graph === 'name') return { at: null, msg: plain(one.msg) }
        const of = body === 'body' && graph === 'graph' && (list === 'steps' || list === 'groups') ? draft.graph[list][index as number] : undefined
        if (!of) return one
        // (A Who is one of four shapes, and the check says each it is not: one line for them all.)
        return { at: of.id, msg: field === 'who' ? 'Who does it is not one the board draws: choose it again' : plain(one.msg) }
      })
      const at = raw.filter(one => typeof one.at === 'string')
      // (Anything else the check refused is said where the request names it.)
      const whole = [...new Set(raw.filter(one => !one.at).map(one => ('at' in one ? String(one.msg) : `${(one.loc ?? []).filter(part => part !== 'body').join('.')}: ${one.msg}`)))]
      if (at.length) {
        const found: Record<string, string[]> = {}
        for (const one of at) if (!found[one.at as string]?.includes(String(one.msg))) (found[one.at as string] ??= []).push(String(one.msg))
        setProblems(found)
        // (Its words in the part's panel, the others' on their ⚠: under a part they lay over its arrows, R57.)
        setPart(at[0].at as string)
        setError(whole.length ? whole.join('; ') : `It cannot run yet: ${at.length === 1 ? 'one part says why' : `${at.length} things to change, each at its part`}.`)
      } else setError(whole.length ? whole.join('; ') : errorText(err))
    }
  }
  const write = async () => {
    if (!actions) return
    setWriting(true)
    setError(null)
    try {
      const drawn = await actions.draftRecipe(sentence.trim())
      open({ name: drawn.name, graph: drawn.graph, from: null }, null, `Drawn by ${drawn.provider_name}${drawn.model_id ? ` (${drawn.model_id})` : ''}: change it as you like, then save it. Nothing is saved yet.`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setWriting(false)
    }
  }
  const deleteIt = async (recipe: Recipe) => {
    if (!actions) return
    setError(null)
    try {
      await actions.deleteRecipe(recipe)
      reload()
      if (first) open(opened(first), recipeKey(first), `${recipe.name} deleted.`)
    } catch (err) {
      setError(errorText(err))
    }
  }
  const why = list && typeof list !== 'string' ? list.writer.why : 'The recipes are not read yet.'
  const chosenPart = draft && part && kindOf(draft.graph, part) ? part : null
  const fromGraph = draft ? before(draft.graph, chosenPart ?? '') : []
  return (
    <>
      <div className="agents-list recipe-list" aria-label="Recipes">
        {typeof list === 'string' && (
          <p role="alert" className="alert">
            The recipes could not be read: {list}
          </p>
        )}
        {list && typeof list !== 'string' && list.broken.map(line => (
          <p key={line} role="alert" className="alert">
            {line}
          </p>
        ))}
        {recipes.map(recipe => (
          <button key={recipeKey(recipe)} type="button" className={`recipe-item${chosen === recipeKey(recipe) ? ' recipe-item-chosen' : ''}`} aria-pressed={chosen === recipeKey(recipe)} onClick={() => open(opened(recipe), recipeKey(recipe))}>
            <b>{recipe.name}</b>
            <span className="muted">
              {summary(recipe.graph)} · {recipe.ready ? 'ready' : recipe.project_id ? 'this folder’s' : 'yours'}
            </span>
          </button>
        ))}
        <button type="button" className="agents-add" onClick={() => open({ name: 'New recipe', graph: emptyGraph(), from: null }, null)}>
          + Draw a new recipe
        </button>
        <div className="recipe-write">
          <b>Or write it</b>
          <textarea
            className="input"
            aria-label="The recipe in words"
            rows={4}
            maxLength={2000}
            placeholder="First the spec writer, then the coder; a security and a UI review at the same time; at most two rounds of fixes; ask me before it goes in."
            value={sentence}
            onChange={e => setSentence(e.target.value)}
          />
          <button type="button" className="btn btn-small" disabled={!sentence.trim() || !!why || writing || !actions} onClick={() => void write()}>
            {writing ? 'Asking the Orchestrator’s model…' : 'Make it a recipe'}
          </button>
          <span className="muted recipe-note">{why ?? 'The Orchestrator’s model draws it on the board; nothing is saved until you save it.'}</span>
        </div>
      </div>
      <div className="recipe-board">
        {draft && (
          <>
            <div className="recipe-head">
              <input className="input recipe-name" aria-label="Recipe’s name" maxLength={60} value={draft.name} disabled={readOnly} onChange={e => setDraft({ ...draft, name: e.target.value })} />
              {draft.from === null && projectId && (
                <select className="input" aria-label="Where it is kept" value={inFolder ? 'folder' : 'koloni'} onChange={e => setInFolder(e.target.value === 'folder')}>
                  <option value="koloni">Kept in KOLONİ, for every folder</option>
                  <option value="folder">Kept in this folder’s .koloni/recipes (in git)</option>
                </select>
              )}
              <span className="grow" />
              {/* Said again before it goes (as a team is): a team that runs by it loses its default. */}
              {draft.from && !draft.from.ready && deleting ? (
                <span className="agents-new-team">
                  <span>
                    Delete {draft.from.name}? {draft.from.project_id ? 'Its file in .koloni/recipes goes too.' : 'A team that runs by it will have no default recipe.'}
                  </span>
                  <button type="button" className="btn btn-small btn-danger" onClick={() => draft.from && void deleteIt(draft.from)}>
                    Delete recipe
                  </button>
                  <button type="button" className="btn btn-small" onClick={() => setDeleting(false)}>
                    Cancel
                  </button>
                </span>
              ) : (
                draft.from &&
                !draft.from.ready && (
                  <button type="button" className="link-btn" onClick={() => setDeleting(true)}>
                    Delete
                  </button>
                )
              )}
              <button type="button" className="btn btn-small" onClick={() => open({ name: `${draft.name} copy`, graph: draft.graph, from: null }, null, readOnly ? 'A copy of a ready recipe: yours to change.' : null)}>
                Copy it
              </button>
              {!readOnly && (
                <button type="button" className="btn btn-small btn-primary" disabled={!actions} onClick={() => void save()}>
                  Save recipe
                </button>
              )}
            </div>
            {error && (
              <div role="alert" className="alert">
                {error}
              </div>
            )}
            <span role="status" className="muted provider-note recipe-status">
              {readOnly ? 'A ready recipe: copy it to change it.' : said}
            </span>
            {/* The tools hang a new part after the chosen one (inside a chosen group); over the board, never on a part. */}
            <div className="recipe-tools" role="toolbar" aria-label="Draw">
              <button type="button" className="recipe-tool" disabled={readOnly} onClick={() => add(addStep(draft.graph, chosenPart))}>
                + Step
              </button>
              <button type="button" className="recipe-tool" disabled={readOnly} onClick={() => add(addGroup(draft.graph, chosenPart))}>
                + All at once
              </button>
              <button
                type="button"
                className="recipe-tool"
                title="From the chosen step back to the one before it, with its findings"
                disabled={readOnly || !chosenPart || !fromGraph.some(id => kindOf(draft.graph, id) === 'step' || kindOf(draft.graph, id) === 'group')}
                onClick={() => chosenPart && change(loopBack(draft.graph, chosenPart))}
              >
                + Loop back
              </button>
              <button type="button" className="recipe-tool" title="Its roles meet in one room" disabled={readOnly} onClick={() => add(addRoom(draft.graph, chosenPart))}>
                + Room
              </button>
              <button type="button" className="recipe-tool" disabled={readOnly} onClick={() => add(addEnd(draft.graph, chosenPart))}>
                + Ask me
              </button>
              <button type="button" className="recipe-tool" title="Every part back where the board puts it" disabled={readOnly} onClick={() => {
                  change(tidy(draft.graph))
                  setOpens(n => n + 1) // (seen afresh, from its top: the dragged parts held it elsewhere)
                }}>
                Tidy up
              </button>
            </div>
            <div className="recipe-flow">
              <ReactFlowProvider key={opens}>
                <Board draft={draft} roles={roles} teams={teams} models={models} chosen={chosenPart} problems={problems} readOnly={readOnly} onChoose={setPart} onChange={change} />
              </ReactFlowProvider>
            </div>
          </>
        )}
      </div>
      {draft && chosenPart ? (
        <PartPanel graph={draft.graph} id={chosenPart} roles={roles} teams={teams} problems={problems[chosenPart] ?? []} readOnly={readOnly} onChange={change} onChoose={setPart} models={models} providers={providers} onModels={onModels} />
      ) : (
        <aside className="role-panel recipe-panel" aria-label="Recipe part">
          <p className="muted">Choose a part of the drawing to see who does it, what it gets and where it goes on.</p>
        </aside>
      )}
    </>
  )
}
