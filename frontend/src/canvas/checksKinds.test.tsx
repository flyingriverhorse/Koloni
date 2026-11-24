import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { Agent, Message } from '../api/types'
import { ChecksPanel } from '../inspector/ChecksPanel'
import { Inspector } from '../inspector/Inspector'
import { CHECK_KINDS } from '../shell/sections/CheckKinds'
import { agent, assistantMessage, convState, run, toolCall } from '../test-fixtures'
import { type Loop, testRows } from './checksLoop'
import type { ChecksData } from './checksNode'
import { deriveGraph } from './deriveGraph'

// Codex's review of PR #25 (dd2d7e3): F1 - this release's kinds of work (Config, Scripts, Code style, Pages) left out of the
// Checks panel and the loop's foot; F2 - a look whose report said MERGE with a blocking finding drawn as a green MERGE card.
// Its probes, as tests.

type Row = NonNullable<Message['checked']>[number]
type Pass = NonNullable<Message['passes']>[number]
const failedRow = (kind: string, text: string): Row => ({
  kind,
  state: 'failed',
  text,
  command: null,
  guessed: false,
  started_at: null,
  counts: null,
})
const section = (rows: Row[], passes: Pass[] = []): Message => ({
  ...assistantMessage('k', 'r', ''),
  role: 'checked',
  agent_id: null,
  checked: rows,
  passes,
})

test.each(CHECK_KINDS.map(([kind]) => kind))(
  'F1: a failed %s check is one of the panel’s and the foot’s rows',
  kind => {
    const row = failedRow(kind, `${kind}: probe failure`)
    expect(testRows([row])).toEqual([row])
  },
)

test.each(['config', 'scripts', 'style', 'ui'])(
  'F1: a turn whose only failure is a %s check shows it when Checks is opened',
  kind => {
    const one = run('r', 'completed')
    const said = `${kind === 'config' ? 'package.json' : 'a.sh'}: does not parse (${kind})`
    const state = convState({ runs: [one], messages: [section([failedRow(kind, said)])] })
    render(<ChecksPanel state={state} run={one} loop={null} openWindow={() => {}} />)
    const tests = screen.getByRole('region', { name: 'Tests' })
    expect(within(tests).getByText(new RegExp(said.replace(/[().]/g, '\\$&')))).toBeInTheDocument()
    expect(within(tests).queryByText('None said yet.')).toBeNull()
  },
)

/** The shape the backend wrote for a MERGE with a blocking finding (backend-review-pass.json, from the scenario's database). */
function blockingMerge(verdict: string, said: string | null) {
  const one = run('r', 'completed')
  const call = toolCall('sreview', 'r', 'spawn_agent', 'succeeded', '{}', {
    provider_call_id: 'koloni_proof_review_rv',
  })
  const reviewer: Agent = {
    ...agent('rv', 'completed', { role_name: 'Reviewer' }),
    run_id: 'r',
    depth: 1,
    parent_agent_id: 'r',
    tool_call_id: call.id,
    name: 'Reviewer',
    report: 'Verdict: MERGE\n\n## Findings\n- auth bypass | kind: bug | role: Coder | blocking',
    findings: [{ what: 'auth bypass', kind: 'code', role: 'Coder', blocking: true }],
  }
  const rows = [
    failedRow('review', 'Review: Reviewer (Local · fake-model) - 1 blocking finding, though its verdict said MERGE'),
    failedRow('review', 'Still on hold after 1 fix rounds: you decide (Fix it)'),
  ]
  const passes: Pass[] = [
    {
      n: 1,
      kind: 'check',
      tests: 'passed',
      looks: [{ agent_id: 'rv', role: 'Reviewer', verdict, said }],
      why: null,
      sent: null,
      fixers: [],
      diagnosis: null,
      tier: null,
    },
  ]
  return convState({
    runs: [one],
    agents: [agent('r', 'completed'), reviewer],
    toolCalls: [call],
    messages: [assistantMessage('a', 'r', 'done'), section(rows, passes)],
  })
}

test('F2: a look that held the work by a blocking finding is a red HOLD card, its report’s MERGE said beside it in the panel', () => {
  const state = blockingMerge('HOLD', 'MERGE')
  const loop = (deriveGraph(state).nodes.find(node => node.kind === 'checks')!.data as ChecksData).loop as Loop
  expect(loop.looks[0]).toMatchObject({ said: 'HOLD · 1 blocking', tone: 'bad' })
  expect(loop.rounds[0].looks[0].verdict).toBe('HOLD · 1 blocking - its report said MERGE')
  render(<Inspector state={state} selectedId="checks:r" onClose={() => {}} onOpenAgent={() => {}} />)
  const panel = screen.getByRole('complementary', { name: 'Inspector' })
  expect(within(panel).getByRole('region', { name: 'Round 1' })).toHaveTextContent(
    'HOLD · 1 blocking - its report said MERGE',
  )
})
