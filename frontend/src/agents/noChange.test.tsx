import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { Message } from '../api/types'
import { AgentSaid } from '../chat/AgentSaid'
import { agent, assistantMessage, convState } from '../test-fixtures'
import { Report } from './agentParts'
import { SpawnRow } from './SpawnRow'

// L1 (Codex's live run, 24 Nov): a Coder said it was done having changed nothing; KOLONİ's record says so on its card.
const coder = agent('r', 'completed', {
  id: 'kid',
  parent_agent_id: 'r',
  role_name: 'Coder',
  depth: 1,
  report: '## Done\nAdded subtract and two tests.',
  changed_nothing: true,
})

test('a sub-agent done with no file changed says so over its report and on its row', () => {
  render(<Report state={convState()} agent={coder} />)
  expect(screen.getByText('No file changed')).toBeInTheDocument()
  expect(screen.getByText(/Added subtract and two tests/)).toBeInTheDocument()
  render(<SpawnRow agent={coder} onSelect={() => {}} />)
  expect(screen.getByRole('button', { name: /Coder/ })).toHaveTextContent('No file changed')
})

test('it says so with no report too', () => {
  render(<Report state={convState()} agent={{ ...coder, report: null }} />)
  expect(screen.getByText('No file changed')).toBeInTheDocument()
  expect(screen.getByText('It wrote no report.')).toBeInTheDocument()
})

test('an agent not marked so says nothing of it', () => {
  for (const marked of [null, undefined, false]) {
    const one = { ...coder, changed_nothing: marked }
    const { unmount } = render(
      <>
        <Report state={convState()} agent={one} />
        <SpawnRow agent={one} onSelect={() => {}} />
      </>,
    )
    expect(screen.getByText(/Added subtract/)).toBeInTheDocument()
    expect(screen.queryByText('No file changed')).not.toBeInTheDocument()
    unmount()
  }
})

test('its report to a CLI Lead, folded, leads with KOLONİ’s word of it', () => {
  const content =
    'Coder finished.\n\nKOLONİ: this agent changed no file. Its record holds no change by it or by an agent it ' +
    'opened; where the report below says it changed a file, it did not.\n\n## Done\nAdded subtract and two tests.' +
    "\n\nWhat it did, from KOLONİ's record: read 2 files, wrote 0, ran 0 commands, 0 web."
  const message: Message = {
    ...assistantMessage('n', 'r', content),
    role: 'agent',
    agent_id: 'r',
    from_agent_id: 'kid',
  }
  render(<AgentSaid message={message} from="Coder" agent={coder} />)
  expect(screen.getByRole('button', { name: 'Coder · done · KOLONİ: this agent changed no file.' })).toBeInTheDocument()
})
