import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { command, toolCall } from '../test-fixtures'
import { ToolRun } from './ToolRun'
import { TurnSteps } from './TurnSteps'

// F411, K4: commands a night job parked and one a judge refused - each call denied to its agent - are said as that.
const calls = ['1', '2', '3'].map(id => toolCall(id, 'r', 'run_command', 'denied', '{"command":"python q.py"}'))
const judged = { kind: 'risk', verdict: 'refuse', why: 'risky' } as ReturnType<typeof command>['judged']
const state = {
  commands: [
    command('k1', 'r', { tool_call_id: '1', status: 'parked' }),
    command('k2', 'r', { tool_call_id: '2', status: 'parked' }),
    command('k3', 'r', { tool_call_id: '3', status: 'refused', judged }),
  ],
  fileChanges: [],
}

test('a turn folded and a run of calls count parked and judge-refused commands as such, not rejected', () => {
  render(
    <>
      <TurnSteps refocus={false} ended="completed" count={3} took={null} calls={calls} state={state}>
        steps
      </TurnSteps>
      <ToolRun calls={calls} state={state}>
        rows
      </ToolRun>
    </>,
  )
  expect(screen.getAllByText('2 parked')).toHaveLength(2)
  expect(screen.getAllByText('1 refused by the judge')).toHaveLength(2)
  expect(screen.queryByText(/rejected/)).toBeNull()
})
