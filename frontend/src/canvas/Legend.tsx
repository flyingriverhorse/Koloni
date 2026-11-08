import { AGENT_STATUS } from '../agents/agentStatus'
import { StatusLabel } from '../shell/StatusLabel'
import { DASH } from './layout'

/** The lines of the canvas, drawn as CanvasView draws them: dash, colour, width, and what each says. */
const LINES: [dash: string | undefined, colour: string, width: number, what: string][] = [
  ['5', 'var(--accent)', 2, 'At work: its dashes move'],
  [undefined, 'var(--border-strong)', 1.5, 'The work: to the Orchestrator, and in a team from its door, step by step - the line splits into a step’s agents and joins again after them'],
  [DASH.spawn, 'var(--border-strong)', 1.5, 'Handed to a sub-agent'],
  [DASH.plan, 'var(--border-strong)', 1.5, 'From an approved plan down to the Orchestrator that carries it out'],
  [DASH.po, 'var(--border-strong)', 1.5, 'From the Orchestrator down to the Assistant PO, asked once its turn ended for follow-up tasks on the To-do list'],
  [DASH.talk, 'var(--border-strong)', 1.5, 'A member’s line to its discussion or room (between teams, from its frame to the lane)'],
  [undefined, 'var(--accent)', 2, 'From a team to its card at its top right: what it shared, noted and remembered (dotted: from an agent with no team to its card, or to a contract’s card from its request’s line)'],
  [DASH.waits, 'var(--border-strong)', 1, 'Waits for a file another agent holds'],
  [DASH.findings, 'var(--warn)', 1.5, 'Findings handed on: from the agent that found them to the one given them; in a team, it runs back over or under the work line'],
  [DASH.talkLine, 'var(--tool-team)', 2, 'Talk between two agents of a team: on the line that already joins them, or else on an arc over or under the work line, round its agents, like findings back - “💬 2 messages”; between two teams, agent to agent in the margin beside their frames. Each pair has its own colour, and a click shows what was said'],
]

/** What the canvas's colours, lines and signs mean, at a glance (the "?" among its buttons). */
export function Legend() {
  return (
    <>
      <div className="kicker">An agent’s state</div>
      <ul className="legend-list legend-states">
        {/* Each word once: a sub-agent asked for and a lead that asks both wait for you. */}
        {[...new Map(Object.values(AGENT_STATUS))].map(([label, colour]) => (
          <li key={label}>
            <StatusLabel color={colour}>{label}</StatusLabel>
          </li>
        ))}
      </ul>
      <div className="kicker">Around a node</div>
      <ul className="legend-list">
        <li>
          <span className="legend-ring legend-ring-running" aria-hidden /> At work
        </li>
        <li>
          <span className="legend-ring legend-ring-approval" aria-hidden /> Waits for you
        </li>
      </ul>
      <div className="kicker">Lines</div>
      <ul className="legend-list">
        {LINES.map(([dash, colour, width, what]) => (
          <li key={what}>
            <svg width="36" height="8" aria-hidden>
              <line x1="0" y1="4" x2="36" y2="4" stroke={colour} strokeWidth={width} strokeDasharray={dash} />
            </svg>
            {what}
          </li>
        ))}
      </ul>
      <div className="kicker">Signs on an agent</div>
      <ul className="legend-list">
        <li>
          <span className="tag tag-warn">N× same error</span> The same failure or result from its own tool calls, counted
        </li>
        <li>
          <span className="muted">last step 12s ago</span> When it last took a step or a tool started or ended. After 5 min with neither it says so (a model may still be writing); after 20 min in one tool, “slow”. Nothing is stopped for it.
        </li>
      </ul>
    </>
  )
}
