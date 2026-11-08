import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { agent, convState, run } from '../test-fixtures'
import { AgentWindow } from './AgentWindow'

const kid = { id: 'kid', parent_agent_id: 'r', role_name: 'Reviewer', task: 'Review hello.py', depth: 1 }
const by = { provider_name: 'Local', model_id: '/models/qwen-4b.gguf' }
const shown = (over: Parameters<typeof agent>[2]) =>
  render(
    <AgentWindow
      state={convState({ runs: [run('r')], agents: [agent('r', 'completed'), agent('r', 'completed', { ...kid, ...over })] })}
      agentId="kid"
      onClose={() => {}}
      onOpenChange={() => {}}
      onSelectAgent={() => {}}
    />,
  )

test('what the Observer said is shown signed, and tagged as an opinion', () => {
  shown({ observation: 'The report says the tests pass; no test run is on record.', observed_by: by, observation_note: null })
  expect(screen.getByText('opinion')).toBeInTheDocument()
  expect(screen.getByText(/Observer \(Local · qwen-4b\): “The report says the tests pass; no test run is on record\.”/)).toBeInTheDocument()
})

test('with no observation the window says why, and calls nothing an opinion', () => {
  shown({ observation: null, observed_by: by, observation_note: 'the request to the Observer failed: model server unreachable' })
  expect(screen.getByText(/Observer \(Local · qwen-4b\): no observation - the request to the Observer failed: model server unreachable/)).toBeInTheDocument()
  expect(screen.queryByText('opinion')).not.toBeInTheDocument()
})

test('where nobody was asked, nothing is said of an observer', () => {
  shown({})
  expect(screen.queryByText(/Observer/)).not.toBeInTheDocument()
})
