import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import { Inspector } from '../inspector/Inspector'
import { agent, assistantMessage, convState, openAgentFold, run, toolCall, userMessage } from '../test-fixtures'
import { AgentWindow } from './AgentWindow'
import { ownSubAgentModel } from './ownWork'
import { SpawnApproval } from './SpawnApproval'

/** The Model line under Details, in the agent window. */
const modelIn = async (name: 'Agent window') => {
  const root = screen.getByRole('region', { name })
  await openAgentFold('Details', root)
  return within(root).getByText('Model', { exact: true }).nextElementSibling
}

const WHY = 'The bug is subtle: it needs the stronger model.'
// A Reviewer the Lead put on another model, with its reason - and a Coder on its role's own.
const picked = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'waiting', { id: 'lead' }),
    agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, provider_name: 'Fast', model_id: 'deep', chosen: true, chosen_why: WHY }),
    agent('r', 'running', { id: 'own', parent_agent_id: 'lead', role_name: 'Coder', depth: 1 }),
  ],
  messages: [userMessage('r', 'look hard')],
})

test('the card says why the agent picked the model, as the agent’s own words', () => {
  const kid = picked.agents[1]
  const { rerender } = render(<SpawnApproval agent={{ ...kid, status: 'proposed' }} openedBy="Lead" onDecide={async () => {}} />)
  expect(screen.getByText('chosen by Orchestrator')).toBeInTheDocument()
  const reason = screen.getByText(WHY)
  expect(reason.tagName).toBe('Q') // in quotes: data, not KOLONİ's words
  expect(reason.parentElement).toHaveTextContent(`Its reason: ${WHY}`)
  // its role's own model: nobody chose it, and there is no reason to show
  rerender(<SpawnApproval agent={{ ...picked.agents[2], status: 'proposed' }} openedBy="Lead" onDecide={async () => {}} />)
  expect(screen.queryByText(/Its reason/)).not.toBeInTheDocument()
})

test('the agent’s window says who chose the model and why, under Details', async () => {
  // (the panel's card has none of it: its window has, under Details)
  render(<AgentWindow state={picked} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(await modelIn('Agent window')).toHaveTextContent(`deep · chosen by Orchestrator: “${WHY}”`)
})

test('a lead whose model followed the message says so in its window - as a model’s guess', async () => {
  const GUESS = 'hard: the failure only shows under load'
  const auto = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { id: 'lead', provider_name: 'Local', model_id: 'big-model', chosen_why: GUESS })],
    messages: [userMessage('r', 'find it')],
  })
  render(<AgentWindow state={auto} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(await modelIn('Agent window')).toHaveTextContent(`big-model · automatic, by a fast model’s guess: “${GUESS}”`)
  expect(screen.queryByText(/chosen by/)).not.toBeInTheDocument()
})

test('a sub-agent the Lead gave a tier says why that tier, not a model’s guess (B-76)', async () => {
  const TIER = 'Check hello.py. Local was not answering: the next balanced model'
  const tiered = convState({
    runs: [run('r', 'running')],
    agents: [
      agent('r', 'waiting', { id: 'lead' }),
      agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, model_id: 'sonnet', chosen_why: TIER }),
    ],
    messages: [userMessage('r', 'check it')],
  })
  render(<AgentWindow state={tiered} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(await modelIn('Agent window')).toHaveTextContent(`sonnet · why this tier: “${TIER}”`)
  expect(screen.queryByText(/guess/)).not.toBeInTheDocument()
})

test('who was asked how hard the message is is said with the guess - and, when nothing came of the question, in a sentence of the app’s own', async () => {
  const GUESS = 'hard: the failure only shows under load'
  const NOTHING =
    'automatic: Fast · quick was asked, and nothing came of it (no answer to go by, or no model of the tier it said) - the Orchestrator’s model is what it would be without the question'
  const asked = { provider_name: 'Fast', model_id: 'quick' }
  const state = (chosen_why: string | null) =>
    convState({
      runs: [run('r', 'running')],
      agents: [agent('r', 'running', { id: 'lead', provider_name: 'Local', model_id: 'big-model', chosen_why, asked_how_hard: asked })],
      messages: [userMessage('r', 'find it')],
    })

  // the answer was read: the guess, and whose it is
  let view = render(<AgentWindow state={state(GUESS)} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(await modelIn('Agent window')).toHaveTextContent(`big-model · automatic, by Fast · quick’s guess: “${GUESS}”`)
  view.unmount()

  // somebody was asked and there is no guess to show: said, so that a question paid for every turn is not unseen
  view = render(<AgentWindow state={state(null)} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(await modelIn('Agent window')).toHaveTextContent(`big-model · ${NOTHING}`)
  expect(screen.queryByText(/guess/)).not.toBeInTheDocument()
})

// Claude Code working natively, with two sub-agents of its own: one it named a model for, one it did not.
const own = convState({
  runs: [run('r', 'running')],
  agents: [agent('r', 'running', { provider_name: 'Claude Code' })],
  messages: [userMessage('r', 'fix it'), assistantMessage('m1', 'r', 'I will ask helpers.')],
  toolCalls: [
    toolCall('2', 'r', 'claude__Agent', 'running', '{"description":"Look around","prompt":"Read hello.py","model":"haiku"}', { origin: 'cli', message_id: 'm1' }),
    toolCall('3', 'r', 'claude__Agent', 'running', '{"description":"Dig deeper","prompt":"Read more"}', { origin: 'cli', message_id: 'm1' }),
  ],
})

test('a CLI’s own sub-agent says whose models it uses, and the model only where the record has it', () => {
  const [named, unnamed] = own.toolCalls
  expect(ownSubAgentModel(named)).toBe('uses Claude Code’s own models, not KOLONİ’s team guide; model asked for: haiku')
  expect(ownSubAgentModel(unnamed)).toBe('uses Claude Code’s own models, not KOLONİ’s team guide; model not reported')
  // in the agent's window (a sub-agent at work is open)
  const view = render(<AgentWindow state={own} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const block = (task: string) => within(screen.getByRole('group', { name: `Own sub-agent: ${task}` }))
  expect(block('Look around').getByText(ownSubAgentModel(named))).toBeInTheDocument()
  expect(block('Dig deeper').getByText(ownSubAgentModel(unnamed))).toBeInTheDocument()
  view.unmount()
  // and in the inspector
  render(<Inspector state={own} selectedId="subagent:3" onClose={() => {}} />)
  expect(within(screen.getByRole('complementary', { name: 'Inspector' })).getByText(ownSubAgentModel(unnamed))).toBeInTheDocument()
})
