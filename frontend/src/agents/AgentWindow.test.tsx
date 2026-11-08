import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { sentAt, topicOf } from '../canvas/thread.fixtures'
import type { Project, Provider } from '../api/types'
import { agent, assistantMessage, command, convState, fileChange, openAgentFold, question, run, toolCall, userMessage } from '../test-fixtures'
import { useApp } from '../state/store'
import { Inspector } from '../inspector/Inspector'
import { toFront } from '../shell/move'
import { AgentWindow, withoutFindings } from './AgentWindow'
import { NOT_WATCHED } from './ownWork'

// More, opened in a window, leaves the store's flag set (the node's Raw opens it so): not for the next test.
afterEach(() => useApp.setState({ agentWindowRaw: false }))

/** One of the folds of the window, by the words its line starts with. */
const fold = (name: string) => screen.getByText(name, { selector: 'summary, summary *' }).closest('details') as HTMLElement

// A lead that is Codex working with its own tools, and a Reviewer it opened.
const state = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'running', { id: 'lead', provider_name: 'Codex', model_id: 'gpt-6' }),
    agent('r', 'completed', { id: 'kid', parent_agent_id: 'lead', tool_call_id: '4', role_name: 'Reviewer', task: 'Review hello.py', depth: 1 }),
  ],
  messages: [
    userMessage('r', 'fix it'),
    { ...assistantMessage('m1', 'r', 'I will fix the greeting.'), agent_id: 'lead' },
    { ...assistantMessage('m2', 'r', 'Fixed and checked.'), agent_id: 'lead' },
    { ...assistantMessage('m3', 'r', 'reviewer words'), agent_id: 'kid' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'edit_file', 'succeeded', '{"path":"hello.py"}', { agent_id: 'lead', message_id: 'm1', origin: 'cli' }),
    toolCall('2', 'r', 'run_command', 'succeeded', '{"command":"python hello.py"}', { agent_id: 'lead', message_id: 'm1', origin: 'cli' }),
    toolCall('3', 'r', 'sonarqube.scan', 'succeeded', '{}', { agent_id: 'lead', message_id: 'm1', origin: 'cli', result: '2 issues' }),
    toolCall('4', 'r', 'spawn_agent', 'succeeded', '{"role":"Reviewer"}', { agent_id: 'lead', message_id: 'm1' }),
  ],
  fileChanges: [fileChange('f1', 'r', { agent_id: 'lead', tool_call_id: '1', path: 'hello.py', origin: 'cli' })],
  commands: [command('k1', 'r', { agent_id: 'lead', tool_call_id: '2', command: 'python hello.py', output: 'hello\n', origin: 'cli' })],
})

test('the window tells what the agent did as plain phases, in order, with the rows to act on; every step as recorded under Details', async () => {
  const onOpenChange = vi.fn()
  const onSelectAgent = vi.fn()
  const { container } = render(
    <AgentWindow state={state} agentId="lead" onClose={() => {}} onOpenChange={onOpenChange} onSelectAgent={onSelectAgent} />,
  )
  expect(screen.getByRole('region', { name: 'Agent window' })).toBeInTheDocument()
  expect(screen.getByText('Orchestrator')).toBeInTheDocument()
  expect(screen.getByText('Codex · gpt-6')).toBeInTheDocument()
  expect(screen.getByText('works with its own tools')).toBeVisible() // on top, not under Details

  // On top: what it did, counted (a command is not a tool as well); its changes open.
  expect(screen.getByText('Did').nextElementSibling).toHaveTextContent('1 file changed · 3 tools · 1 command · 2 steps')
  // What it did, in words: a phase a kind, what it said before it quoted, a tool nothing else names by its name.
  const story = container.querySelector('.agent-story') as HTMLElement
  expect(within(story).getAllByRole('heading', { level: 4 }).map(h => h.textContent)).toEqual([
    'Changed hello.py',
    'Ran python hello.py',
    'Used sonarqube.scan',
    'Opened Reviewer',
    'Said',
  ])
  expect(story).toHaveTextContent('“I will fix the greeting.”')
  expect(story).toHaveTextContent('Fixed and checked.')
  expect(container).not.toHaveTextContent('reviewer words')  // another agent's conversation

  await userEvent.click(within(story).getByText('What happened'))
  await userEvent.click(within(story).getByRole('button', { name: /python hello\.py/ }))
  expect(screen.getByText('hello')).toBeInTheDocument()  // the command's own output
  await userEvent.click(within(story).getByRole('button', { name: 'View diff of hello.py' }))
  expect(onOpenChange).toHaveBeenCalledWith('f1')
  onOpenChange.mockClear()
  await userEvent.click(within(fold('Changes')).getByRole('button', { name: 'View diff of hello.py' }))
  expect(onOpenChange).toHaveBeenCalledWith('f1')
  await userEvent.click(within(story).getByRole('button', { name: /Reviewer.*Review hello\.py/ }))
  expect(onSelectAgent).toHaveBeenCalledWith('kid')
  // and among its sub-agents, counted on the fold's line
  const kids = await openAgentFold('Sub-agents')
  expect(kids.querySelector('summary')).toHaveTextContent('Sub-agents 1')
  onSelectAgent.mockClear()
  await userEvent.click(within(kids).getByRole('button', { name: /Reviewer.*Review hello\.py/ }))
  expect(onSelectAgent).toHaveBeenCalledWith('kid')

  // Every step as recorded: folded in Details, the raw list in order.
  expect(fold('Details')).not.toHaveAttribute('open')
  const steps = await openAgentFold('Every step as recorded')
  expect(steps.querySelector('summary')).toHaveTextContent('2 steps')
  const text = steps.textContent ?? ''
  const order = ['I will fix the greeting.', 'hello.py', 'python hello.py', 'sonarqube.scan', 'Reviewer', 'Fixed and checked.']
  expect(order.map(piece => text.indexOf(piece)).every((at, i, all) => at >= 0 && (i === 0 || at > all[i - 1]))).toBe(true)
})

test('an agent that used only KOLONİ’s tools is not marked, and the window closes', async () => {
  const onClose = vi.fn()
  render(<AgentWindow state={state} agentId="kid" onClose={onClose} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Reviewer')).toBeInTheDocument()
  // done with no report: said so, and what it said is in its story
  expect(screen.getByText('It wrote no report.')).toBeVisible()
  expect(screen.getByText('reviewer words')).toBeVisible()
  expect(screen.queryByText('works with its own tools')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close agent window' }))
  expect(onClose).toHaveBeenCalled()
})

test('the window says which of KOLONİ’s rules nobody watches the way its CLI runs, from its start (K-native-not)', () => {
  const rules = ['reading secret files (.env, keys): its read-only commands run without asking', 'reading files outside the project, the same way']
  const here = 'its commands run on this machine, not in the project’s Docker'
  useApp.setState({ providers: [{ name: 'Codex', kind: 'codex_cli', not_watched: { native: rules }, not_watched_in_docker: { native: [...rules, here] } }] as unknown as Provider[] })
  try {
    // Nothing of its own done yet: said all the same.
    const fresh = convState({ runs: [run('r', 'running')], agents: [agent('r', 'running', { id: 'lead', provider_name: 'Codex', provider_mode: 'native' })] })
    render(<AgentWindow state={fresh} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    expect(screen.getByText('works with its own tools')).toBeVisible()
    const note = screen.getByText(NOT_WATCHED).closest('details') as HTMLElement
    expect(note).not.toHaveAttribute('open')
    expect(within(note).getAllByRole('listitem').map(item => item.textContent)).toEqual(rules)
    cleanup()
    // Its project runs its commands in Docker: its CLI's own run on this machine, and it says so.
    useApp.setState({ projects: [{ id: 'p', exec_location: 'docker' }] as Project[], projectId: 'p' })
    render(<AgentWindow state={fresh} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    expect(screen.getByText(here)).toBeInTheDocument()
  } finally {
    useApp.setState({ providers: [], projects: [], projectId: null })
  }
})

test('the window says whose work the agent was handed, each a link to that agent - of another chat too, by name (B-366)', async () => {
  // K-devir-1: one of this chat by its name and time, opened on a click. B-366 (live): "Handed on from: Coder (08:16 PM),
  // Coder 2 (08:14 PM), an agent of another chat" - the third nameless; read as text first it was ", , an agent of
  // another chat". Its name and chat are the server's to say; one sub-agent with no name of its own is its role.
  const handed = {
    ...state,
    agents: [
      ...state.agents,
      agent('r', 'completed', { id: 'c1', parent_agent_id: 'lead', role_name: 'Coder', name: '', depth: 1 }),
      agent('r', 'running', { id: 'next', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, handed_from: ['kid', 'c1', 'elsewhere', 'gone'] }),
    ],
  }
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      const one = { agent_id: 'elsewhere', agent_role: 'Coder', agent_name: 'Coder 3', conversation_id: 'other', conversation_title: 'Tags', at: '2026-11-03T20:14:00Z' }
      return new Response(JSON.stringify([one]), { status: 200 })
    }),
  )
  const open = vi.spyOn(useApp.getState(), 'openConversation').mockResolvedValue()
  useApp.setState({ openConversation: open })
  const onSelectAgent = vi.fn()
  try {
    render(<AgentWindow state={handed} agentId="next" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={onSelectAgent} />)
    const row = screen.getByText('Handed on from').nextElementSibling as HTMLElement
    expect(await within(row).findByRole('button', { name: /^Coder 3 \(/ })).toBeInTheDocument()
    expect(asked).toEqual(['/api/agents/next/handed'])
    expect(row).toHaveTextContent(/^Reviewer \(.+\), Coder \(.+\), Coder 3 \(.+\) in chat «Tags», an earlier agent$/)
    // R167: each one an item of a list, its words and its comma in it - read in order, no ", , in chat" before the names.
    const items = within(row).getAllByRole('listitem')
    expect(items.map(item => item.textContent)).toEqual([
      expect.stringMatching(/^Reviewer \(.+\), $/),
      expect.stringMatching(/^Coder \(.+\), $/),
      expect.stringMatching(/^Coder 3 \(.+\) in chat «Tags», $/),
      'an earlier agent',
    ])
    await userEvent.click(within(row).getByRole('button', { name: /^Reviewer/ }))
    expect(onSelectAgent).toHaveBeenCalledWith('kid')
    await userEvent.click(within(row).getByRole('button', { name: /^Coder 3/ }))
    expect(open).toHaveBeenCalledWith('other')
  } finally {
    vi.unstubAllGlobals()
    open.mockRestore()
  }
  cleanup()
  // nothing handed: no row
  render(<AgentWindow state={state} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.queryByText('Handed on from')).not.toBeInTheDocument()
})

test('an agent that is gone shows nothing, and one that has not said anything says so', () => {
  const { container, rerender } = render(
    <AgentWindow state={state} agentId="nope" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />,
  )
  expect(container).toBeEmptyDOMElement()
  const quiet = convState({ runs: [run('r')], agents: [agent('r')] })
  rerender(<AgentWindow state={quiet} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
})

test('the window says who picked the model, and when its name comes from the CLI’s settings', async () => {
  const picked = convState({
    runs: [run('r', 'running')],
    agents: [
      agent('r', 'waiting', { id: 'lead' }),
      agent('r', 'running', {
        id: 'kid',
        parent_agent_id: 'lead',
        role_name: 'Coder',
        depth: 1,
        provider_name: 'Codex',
        model_id: 'gpt-5.5-codex',
        model_from: 'settings',
        chosen: true,
      }),
    ],
  })
  const { rerender } = render(
    <AgentWindow state={picked} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />,
  )
  expect(screen.getByText("Codex · gpt-5.5-codex (from Codex's settings)")).toBeInTheDocument()
  await openAgentFold('Details')
  expect(screen.getByText('Model').nextElementSibling).toHaveTextContent("gpt-5.5-codex (from Codex's settings) · chosen by Orchestrator")
  rerender(<AgentWindow state={picked} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.queryByText(/chosen by/)).not.toBeInTheDocument()
})

test('an agent asked for Copilot’s auto says the model auto picked, and why, in its window', async () => {
  const note = "Copilot's auto picked gpt-6-luna: “Auto selected GPT-6 Luna since the task has low complexity.”"
  const picked = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { id: 'lead', provider_name: 'Copilot', model_id: 'gpt-6-luna', model_from: 'auto', effort_note: note })],
  })
  render(<AgentWindow state={picked} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Copilot · auto → gpt-6-luna')).toBeInTheDocument()
  await openAgentFold('Details')
  expect(screen.getByText('Model').nextElementSibling).toHaveTextContent(/^auto → gpt-6-luna$/)
  expect(screen.getByText(note)).toBeInTheDocument()
})

test('an agent on a Copilot model whose row is Long says "context: long" by its model; any other says nothing (R166)', async () => {
  const copilot = (context: string | null, base_url: string | null = null) =>
    [{ name: 'Copilot', kind: 'copilot_cli', base_url, models: [{ name: 'gpt-x', context }, { name: 'gpt-y', context: null }] }] as unknown as Provider[]
  const on = (model_id: string) => convState({ runs: [run('r', 'running')], agents: [agent('r', 'running', { id: 'lead', provider_name: 'Copilot', model_id })] })
  const view = (model_id: string, providers: Provider[]) => (
    <AgentWindow state={on(model_id)} providers={providers} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />
  )
  const { rerender } = render(view('gpt-x', copilot('long_context')))
  await openAgentFold('Details')
  const model = () => screen.getByText('Model').nextElementSibling
  expect(model()).toHaveTextContent(/^gpt-x · context: long$/)
  for (const [id, providers] of [['gpt-y', copilot('long_context')], ['gpt-x', copilot('default')], ['gpt-x', copilot('long_context', 'http://127.0.0.1:1')]] as const) {
    rerender(view(id, providers))
    expect(model()).not.toHaveTextContent('context')
  }
})

test('a tool of its own that is neither a command nor a change is marked too', async () => {
  render(<AgentWindow state={state} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  // (its step's rows are drawn once that step is unfolded)
  await userEvent.click(within(screen.getByRole('heading', { name: 'Used sonarqube.scan' }).closest('li')!).getByText('What it did'))
  expect(screen.getByRole('button', { name: /sonarqube.scan.*own tool/ })).toBeInTheDocument()
})

test('an agent on a CLI that only reads says so, and that its role’s tools do not apply', async () => {
  const reading = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { id: 'lead', provider_name: 'agy', model_id: 'gemini-3.8-flash-low', provider_mode: 'reads' })],
    messages: [userMessage('r', 'look'), { ...assistantMessage('m1', 'r', 'Looking.'), agent_id: 'lead' }],
    toolCalls: [
      toolCall('1', 'r', 'agy__view_file', 'succeeded', '{}', { agent_id: 'lead', message_id: 'm1', origin: 'cli' }),
      toolCall('2', 'r', 'agy__run_command', 'denied', '{}', { agent_id: 'lead', message_id: 'm1', origin: 'cli', result: 'refused by the CLI: Permission denied' }),
    ],
  })
  const { rerender } = render(<AgentWindow state={reading} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  // said on top, without a click; why, under More
  expect(screen.getByText('reads only', { selector: '.tag' })).toBeVisible()
  await openAgentFold('Details')
  // what is true: how it was started - not that nothing can change
  expect(screen.getByRole('note')).toHaveTextContent(
    'Reads only: on this provider it works with the CLI’s own tools, and the CLI was started without leave to write or run; your own agy settings can allow more. The tools of its role, listed above, do not apply.',
  )
  expect(screen.queryByText('works with its own tools')).not.toBeInTheDocument()
  // the step the CLI refused is not shown as done
  expect(within(await openAgentFold('Every step as recorded')).getByRole('button', { name: /agy__run_command.*own tool.*rejected/ })).toBeInTheDocument()

  // a command of its own on record: the tag no longer reads as if nothing got through
  const ran = { ...reading, commands: [command('c1', 'r', { agent_id: 'lead', origin: 'cli' })] }
  rerender(<AgentWindow state={ran} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent(/^Reads only \(your agy settings let something through\):/)
  expect(screen.getByText('reads only (your agy settings let something through)', { selector: '.tag' })).toBeVisible()
  // the same for a change; another agent's command says nothing about this one
  const wrote = { ...reading, fileChanges: [fileChange('f1', 'r', { agent_id: 'lead', origin: 'cli' })] }
  rerender(<AgentWindow state={wrote} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent(/^Reads only \(your agy settings let something through\):/)
  const other = { ...reading, commands: [command('c1', 'r', { agent_id: 'someone-else' })] }
  rerender(<AgentWindow state={other} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent(/^Reads only: /)
})

// --- topics (slice 18b) ------------------------------------------------------------------------

/** Three turns of one topic; the Coder of each goes on from the Coder of the turn before. */
function chained() {
  const s = topicOf(3)
  return {
    ...s,
    messages: [
      ...s.messages,
      { ...assistantMessage('c1a', 't1', 'I will change the greeting.'), agent_id: 'coder-t1' },
      { ...assistantMessage('c1b', 't1', 'report 1'), agent_id: 'coder-t1' },
      { ...assistantMessage('c2a', 't2', 'report 2'), agent_id: 'coder-t2' },
      { ...assistantMessage('c3a', 't3', 'Working on turn three.'), agent_id: 'coder-t3' },
    ],
    toolCalls: [
      toolCall('1', 't1', 'edit_file', 'succeeded', '{"path":"hello.py"}', { agent_id: 'coder-t1', message_id: 'c1a' }),
      toolCall('2', 't3', 'read_file', 'succeeded', '{"path":"third.py"}', { agent_id: 'coder-t3', message_id: 'c3a' }),
    ],
    fileChanges: [fileChange('f1', 't1', { agent_id: 'coder-t1', tool_call_id: '1', path: 'hello.py' })],
  }
}
const open = (state: ReturnType<typeof chained>, agentId: string, onSelectAgent = vi.fn()) => {
  render(<AgentWindow state={state} agentId={agentId} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={onSelectAgent} />)
  return onSelectAgent
}

test('an agent that goes on from an earlier turn says so, and has its earlier work above this turn’s - folded until asked for', async () => {
  open(chained(), 'coder-t3')
  // on its task's line
  expect(screen.getByText(/^Asked by/).closest('p')).toHaveTextContent(`(continues from the ${sentAt(2)} message)`)
  // this turn's work is there as ever; the earlier turns' is behind one line, with how much
  await openAgentFold('Every step as recorded')
  expect(screen.getByText('Working on turn three.')).toBeVisible()
  const earlier = fold('Earlier work')
  expect(earlier.querySelector('summary')).toHaveTextContent(`Earlier work the ${sentAt(1)} and ${sentAt(2)} messages · 1 file`)
  expect(earlier).not.toHaveAttribute('open')
  expect(screen.queryByText('I will change the greeting.')).not.toBeInTheDocument()

  await userEvent.click(within(earlier).getByText('Earlier work'))
  expect(earlier).toHaveAttribute('open')
  // link by link, oldest first: the turn, its task, what it did, its report
  const links = screen.getAllByRole('group', { name: /^The .+ message$/ })
  expect(links.map(link => link.getAttribute('aria-label'))).toEqual([`The ${sentAt(1)} message`, `The ${sentAt(2)} message`])
  expect(links[0]).toHaveTextContent('task 1')
  expect(links[0]).toHaveTextContent('I will change the greeting.')
  expect(within(links[0]).getByText('hello.py')).toBeInTheDocument()
  expect(within(links[0]).getByText('report 1')).toBeInTheDocument()
  expect(links[1]).toHaveTextContent('task 2')
  // what it said last is its report: said once, under that name
  expect(within(links[1]).getAllByText('report 2')).toHaveLength(1)
  // nothing of this turn's work is in there
  expect(links.some(link => link.textContent?.includes('Working on turn three.'))).toBe(false)
})

test('a link that ended without a report says so; an agent that started clean has no earlier work', async () => {
  const s = chained()
  s.agents = s.agents.map(a => (a.id === 'coder-t1' ? { ...a, report: null, status: 'failed' as const } : a))
  s.messages = s.messages.filter(m => m.id !== 'c1b')
  open(s, 'coder-t2')
  expect(fold('Earlier work').querySelector('summary')).toHaveTextContent(`the ${sentAt(1)} message`)
  await openAgentFold('Earlier work')
  expect(screen.getByRole('group', { name: `The ${sentAt(1)} message` })).toHaveTextContent('It ended without a report.')
  cleanup()
  open(s, 'coder-t1')
  expect(screen.queryByText('Earlier work')).not.toBeInTheDocument()
  expect(screen.queryByText(/continues from/)).not.toBeInTheDocument()
})

test('an agent a later one went on from says in which turn, and the line leads there', async () => {
  const onSelectAgent = open(chained(), 'coder-t1')
  await userEvent.click(screen.getByRole('button', { name: `went on in the ${sentAt(2)} message` }))
  expect(onSelectAgent).toHaveBeenCalledWith('coder-t2')
  cleanup()
  // the newest link went on nowhere; a lead is not said to go on
  open(chained(), 'coder-t3')
  expect(screen.queryByRole('button', { name: /^went on in/ })).not.toBeInTheDocument()
  cleanup()
  open(chained(), 't1')
  expect(screen.queryByRole('button', { name: /^went on in/ })).not.toBeInTheDocument()
  expect(screen.queryByText('Earlier work')).not.toBeInTheDocument()
})

test('the window shows what of all the agent sent was read again from the cache and written to it, where its provider said', async () => {
  const told = convState({ runs: [run('r')], agents: [agent('r', 'completed', { cache_read_tokens: 400000, cache_write_tokens: 500000 })] })
  const { rerender } = render(<AgentWindow state={told} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('400,000 read again from the cache · 500,000 written to it')).toBeInTheDocument()
  // a provider that said nothing of a cache: nothing is shown, and never a zero
  rerender(<AgentWindow state={convState({ runs: [run('r')], agents: [agent('r', 'completed')] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('region', { name: 'Agent window' })).not.toHaveTextContent(/cache/)
})

test("a Copilot agent's window says what it spent in Copilot's own unit beside its tokens, and nothing where it said none", async () => {
  const copilot = agent('r', 'completed', { input_tokens: 22674, output_tokens: 36, nano_aiu: 448558500, premium_requests: 2 })
  const { rerender } = render(<AgentWindow state={convState({ runs: [run('r')], agents: [copilot] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent('22,674 in / 36 out · 0.45 AI credits')
  const other = agent('r', 'completed', { input_tokens: 22674, output_tokens: 36 })
  rerender(<AgentWindow state={convState({ runs: [run('r')], agents: [other] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent(/^22,674 in \/ 36 out$/)
})

test('the window says how full its context is, how many messages were summarised, and the summary can be read', async () => {
  const summarised = agent('r', 'completed', { input_tokens: 620, context_window: 1000, summarised: 2, summary: 'hello.py prints hi' })
  const { rerender } = render(<AgentWindow state={convState({ runs: [run('r')], agents: [summarised] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent('62% · 620 in / unknown out')
  expect(screen.getByRole('meter', { name: 'Context used' })).toHaveAttribute('value', '620')
  const told = screen.getByText('2 messages summarised for its model')
  expect(screen.getByText('hello.py prints hi')).not.toBeVisible()
  await userEvent.click(told)
  expect(screen.getByText('hello.py prints hi')).toBeVisible()
  expect(screen.getByText('hello.py prints hi')).toHaveClass('summary-text') // its lines kept (pre-wrap)
  // none could be made: said, and nothing is said to be summarised; an unknown window: no fill
  const failed = agent('r', 'completed', { input_tokens: 620, summary_note: 'Its earlier conversation could not be summarised (down): its older tool outputs are left out instead.' })
  rerender(<AgentWindow state={convState({ runs: [run('r')], agents: [failed] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText(/could not be summarised \(down\)/)).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Agent window' })).not.toHaveTextContent(/summarised for its model/)
  // an unknown window: no fill, and no bar
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent(/^620 in \/ unknown out$/)
  expect(screen.queryByRole('meter')).not.toBeInTheDocument()
})

test('89j: while its CLI works the window says how full it says its context is, and its plan step by step, as text', async () => {
  const working = agent('r', 'running')
  const live = {
    r: {
      context: { used: 34000, window: 100000 },
      plan: [
        { step: 'Read <b>hello.py</b>', status: 'completed' as const },
        { step: 'Fix it', status: 'inProgress' as const },
      ],
      queue: null,
    },
  }
  render(<AgentWindow state={convState({ runs: [run('r')], agents: [working], live })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  // (no tokens on record yet: its CLI says them at its end)
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent(/^34% full$/)
  expect(screen.getByRole('meter', { name: 'Context used' })).toHaveAttribute('value', '34000')
  const steps = within(screen.getByText('Plan').nextElementSibling as HTMLElement).getAllByRole('listitem')
  expect(steps.map(one => one.textContent)).toEqual(['✓ Read <b>hello.py</b>', '▸ Fix it'])
  expect(steps[1]).toHaveClass('agent-plan-inProgress')
  expect(screen.queryByText('Queue')).toBeNull()
})

test('K-qoder-kuyruk: while Qoder’s model is queued the window says for how long, in one line that is updated in place', () => {
  const working = agent('r', 'running')
  const queued = (elapsed_s: number) => ({ r: { context: null, plan: null, queue: { elapsed_s, max_s: 3600, available: false } } })
  const { rerender } = render(<AgentWindow state={convState({ runs: [run('r')], agents: [working], live: queued(163) })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Queue').nextElementSibling).toHaveTextContent(
    "Qoder: in the model's queue for 2 min 43 s (waits up to 60 min), the service says it is not available",
  )
  rerender(<AgentWindow state={convState({ runs: [run('r')], agents: [working], live: queued(193) })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getAllByText(/in the model's queue/)).toHaveLength(1)
  expect(screen.getByText('Queue').nextElementSibling).toHaveTextContent(/for 3 min 13 s/)
})

test('the working state is shown under the context line and the user can correct it (slice 59d)', async () => {
  const asked = vi.fn(async () => new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', asked)
  const summarised = agent('r', 'running', { input_tokens: 620, context_window: 1000, summarised: 2, summary: '## Goal\n- greet', summary_correctable: true })
  render(<AgentWindow state={convState({ runs: [run('r')], agents: [summarised] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  const own = screen.getByRole('region', { name: 'Agent window' })
  // Under the context line, above the folds below it: not at the end of its feed.
  expect(own.querySelector('.working-state')?.compareDocumentPosition(fold('Every step as recorded'))).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  await userEvent.click(screen.getByText('2 messages summarised for its model'))
  // A long one scrolls: reachable from the keyboard, by its name.
  expect(screen.getByRole('region', { name: 'Working state' })).toHaveAttribute('tabindex', '0')
  await userEvent.click(screen.getByRole('button', { name: 'Edit working state' }))
  expect(screen.getByText(/Its model is sent your words from its next step on/)).toBeInTheDocument()
  const box = screen.getByRole('textbox', { name: 'Working state' })
  expect(box).toHaveValue('## Goal\n- greet')
  await userEvent.clear(box)
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled() // never an empty one
  await userEvent.type(box, 'greet in Turkish')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(asked).toHaveBeenCalledWith('/api/agents/r/summary', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ summary: 'greet in Turkish', summarised: 2 }) }))
  // Saved: back to reading it (the agent's update brings the new words), where it was.
  expect(screen.queryByRole('textbox', { name: 'Working state' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Edit working state' })).toHaveFocus()
  vi.unstubAllGlobals()
})

test('a draft sends how much was summarised when Edit was pressed: summarised again since, the refusal is said', async () => {
  const detail = 'it was summarised again since you began: edit the new working state'
  const asked = vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 409 }))
  vi.stubGlobal('fetch', asked)
  const lead = agent('r', 'completed', { summarised: 2, summary: 'S1', summary_correctable: true })
  const show = (shown: ReturnType<typeof agent>) => (
    <AgentWindow state={convState({ runs: [run('r')], agents: [shown] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />
  )
  const { rerender } = render(show(lead))
  await openAgentFold('Details')
  await userEvent.click(screen.getByText('2 messages summarised for its model'))
  await userEvent.click(screen.getByRole('button', { name: 'Edit working state' }))
  // Compacted meanwhile: the agent's update comes while the draft is open.
  rerender(show({ ...lead, summarised: 4, summary: 'S2' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Working state' }), ' more')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(asked).toHaveBeenCalledWith('/api/agents/r/summary', expect.objectContaining({ body: JSON.stringify({ summary: 'S1 more', summarised: 2 }) }))
  expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  vi.unstubAllGlobals()
})

test('the working state is offered for correcting only where a model is still to read it (slice 59d)', async () => {
  const lead = agent('r', 'completed', { id: 'lead', summarised: 2, summary: 'S', summary_correctable: true })
  const later = agent('r', 'running', { id: 'next', continues_id: 'lead' })
  const show = async (agents: ReturnType<typeof agent>[], id: string) => {
    render(<AgentWindow state={convState({ runs: [run('r')], agents })} agentId={id} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    await openAgentFold('Details')
  }
  // A finished lead: the next turn's lead goes on from it.
  await show([lead], 'lead')
  await userEvent.click(screen.getByText('2 messages summarised for its model'))
  await userEvent.click(screen.getByRole('button', { name: 'Edit working state' }))
  expect(screen.getByText(/The Orchestrator of your next message goes on from your words/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.getByRole('button', { name: 'Edit working state' })).toHaveFocus()
  cleanup()
  // Once a later lead goes on from it, or where the server says no model will read it: not offered.
  await show([lead, later], 'lead')
  expect(screen.queryByRole('button', { name: 'Edit working state' })).not.toBeInTheDocument()
  cleanup()
  await show([{ ...lead, summary_correctable: false }], 'lead')
  expect(screen.queryByRole('button', { name: 'Edit working state' })).not.toBeInTheDocument()
})

test('where its service refused the level it was sent, the window says so', async () => {
  const note = 'Cloud refused reasoning level high: this step was asked again without one, and none is sent to it until the provider is changed.'
  render(<AgentWindow state={convState({ runs: [run('r')], agents: [agent('r', 'completed', { effort_note: note })] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText(note)).toBeVisible()
})

test('where a step was asked again after a short failure of its provider, the window says so', async () => {
  const note = 'A step was asked again once, after a short failure of its provider: model server returned 503: overloaded'
  render(<AgentWindow state={convState({ runs: [run('r')], agents: [agent('r', 'completed', { retry_note: note })] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText(note)).toBeVisible()
})

test('Compact now, beside the context line: only for a lead KOLONİ compacts, why not while at work, and what came of it (slice 77a)', async () => {
  const asked = vi.fn(async () => new Response(JSON.stringify(agent('r', 'completed', { summarised: 4, summary: 'S' })), { status: 200 }))
  vi.stubGlobal('fetch', asked)
  const show = async (agents: ReturnType<typeof agent>[], id = 'r') => {
    render(<AgentWindow state={convState({ runs: [run('r')], agents })} agentId={id} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    await openAgentFold('Details')
  }
  await show([agent('r', 'completed', { summarised: 2 })])
  await userEvent.click(screen.getByRole('button', { name: 'Compact now' }))
  expect(asked).toHaveBeenCalledWith('/api/agents/r/compact', expect.objectContaining({ method: 'POST' }))
  expect(await screen.findByText('Compacted: 2 messages more summarised.')).toHaveAttribute('role', 'status')
  cleanup()
  // At work: not asked, and the reason is said.
  asked.mockClear()
  await show([agent('r', 'running')])
  const button = screen.getByRole('button', { name: 'Compact now' })
  expect(button).toHaveAttribute('aria-disabled', 'true')
  expect(button).toHaveAccessibleDescription(/It is at work: it is compacted at its next step/)
  await userEvent.click(button)
  expect(asked).not.toHaveBeenCalled()
  expect(screen.getByText(/Compact it once its work is over/)).toHaveAttribute('role', 'status') // (beside Tell …: two live regions)
  cleanup()
  // A later agent goes on from it: that one is the one to compact.
  await show([agent('r', 'completed', { id: 'lead' }), agent('r', 'running', { id: 'next', continues_id: 'lead' })], 'lead')
  expect(screen.getByRole('button', { name: 'Compact now' })).toHaveAccessibleDescription(/compact that one/)
  cleanup()
  // A CLI that goes on in its own session compacts that itself; a sub-agent is compacted at its steps: no button.
  await show([agent('r', 'completed', { provider_mode: 'native', compacts_itself: true })])
  expect(screen.queryByRole('button', { name: 'Compact now' })).not.toBeInTheDocument()
  cleanup()
  // One that starts each turn anew (agy) is KOLONİ's to compact.
  await show([agent('r', 'completed', { provider_mode: 'reads' })])
  expect(screen.getByRole('button', { name: 'Compact now' })).toBeInTheDocument()
  cleanup()
  await show([agent('r', 'completed', { id: 'lead' }), agent('r', 'completed', { id: 'kid', parent_agent_id: 'lead', depth: 1 })], 'kid')
  expect(screen.queryByRole('button', { name: 'Compact now' })).not.toBeInTheDocument()
  cleanup()
  // Nothing older yet: said so.
  asked.mockResolvedValueOnce(new Response(JSON.stringify(agent('r', 'completed')), { status: 200 }))
  await show([agent('r', 'completed')])
  await userEvent.click(screen.getByRole('button', { name: 'Compact now' }))
  expect(await screen.findByText('Nothing older to summarise yet.')).toHaveAttribute('role', 'status')
  cleanup()
  // Its model could not write one: why, as its record says.
  const note = 'Its earlier conversation could not be summarised (it said nothing): its older tool outputs are left out instead.'
  asked.mockResolvedValueOnce(new Response(JSON.stringify(agent('r', 'completed', { summary_note: note })), { status: 200 }))
  await show([agent('r', 'completed')])
  await userEvent.click(screen.getByRole('button', { name: 'Compact now' }))
  expect(await screen.findByText(`Not compacted: ${note}`)).toHaveAttribute('role', 'status')
  vi.unstubAllGlobals()
})

test('while Compact now works, its working state cannot be corrected: the summary being made would replace it (slice 77a)', async () => {
  let answer: (r: Response) => void = () => {}
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(done => (answer = done))))
  const lead = agent('r', 'completed', { summarised: 2, summary: 'S', summary_correctable: true })
  render(<AgentWindow state={convState({ runs: [run('r')], agents: [lead] })} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  await userEvent.click(screen.getByText('2 messages summarised for its model'))
  expect(screen.getByRole('button', { name: 'Edit working state' })).toBeEnabled()
  await userEvent.click(screen.getByRole('button', { name: 'Compact now' }))
  expect(screen.getByRole('button', { name: 'Edit working state' })).toBeDisabled()
  answer(new Response(JSON.stringify({ ...lead, summarised: 3 }), { status: 200 }))
  expect(await screen.findByText('Compacted: 1 message more summarised.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Edit working state' })).toBeEnabled()
  vi.unstubAllGlobals()
})

test('with More open on the raw stream, the working state stays one block while the turn goes on (B-98)', () => {
  useApp.setState({ agentWindowRaw: true })
  try {
    const lead = agent('r', 'running', { summarised: 2, summary: 'S', summary_correctable: true })
    const at = (n: number) =>
      convState({
        runs: [run('r', 'running')],
        agents: [{ ...lead, summarised: n, retry_note: n % 2 ? 'asked again' : null }],
        messages: Array.from({ length: n }, (_, i) => assistantMessage(`m${i}`, 'r', `said ${i}`)),
      })
    const { container, rerender } = render(<AgentWindow state={at(2)} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    for (let n = 3; n < 8; n++) rerender(<AgentWindow state={at(n)} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
    expect(container.querySelectorAll('.working-state')).toHaveLength(1)
  } finally {
    useApp.setState({ agentWindowRaw: false })
  }
})

// --- design A, "Report first": the panel a report card, the window the whole story -------------------

const done = convState({
  runs: [run('r', 'completed')],
  agents: [agent('r', 'completed', {
    task: 'Make it say goodbye instead.', report: 'The coder changed it: it says goodbye. Then it checked.',
    input_tokens: 380, output_tokens: 36, context_window: 1000,
  })],
  messages: [userMessage('r', 'go'), assistantMessage('a1', 'r', ''), assistantMessage('a2', 'r', 'The coder changed it: it says goodbye. Then it checked.')],
  toolCalls: [
    toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"farewell.py"}', { message_id: 'a1' }),
    toolCall('2', 'r', 'write_file', 'succeeded', '{"path":"farewell.py"}', { message_id: 'a1' }),
  ],
  fileChanges: [fileChange('f1', 'r', { tool_call_id: '2', path: 'farewell.py', additions: 1, deletions: 1 })],
})
const folds = (root: HTMLElement) =>
  Array.from(root.querySelectorAll('details.agent-fold')).map(d => `${d.hasAttribute('open') ? 'open' : 'folded'}: ${d.querySelector('summary')?.textContent}`)
const numbers = (root: HTMLElement) => Array.from(root.querySelectorAll('.agent-numbers > *')).map(el => el.textContent)

test('the window reads top to bottom: who asked what, its report, its numbers, what it did, its changes; Details folded at the end', () => {
  render(<AgentWindow state={done} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const own = screen.getByRole('region', { name: 'Agent window' })
  expect(screen.getByText(/^Asked by/).closest('p')).toHaveTextContent('Asked by you: Make it say goodbye instead.')
  expect(Array.from(own.querySelectorAll('h3')).map(h => h.textContent)).toEqual(['Report', 'What it did'])
  expect(screen.getByText('Report').nextElementSibling).toHaveTextContent('The coder changed it: it says goodbye. Then it checked.')
  expect(numbers(own)).toEqual(['Did', '1 file changed · 2 tools · 0 commands · 1 step', 'Tokens', '380 in / 36 out'])
  // its report is on top: the story ends with its writing it, not with its words again
  expect(Array.from(own.querySelectorAll('.agent-story h4')).map(h => h.textContent)).toEqual(['Looked around', 'Changed farewell.py', 'Wrote its report'])
  expect(folds(own)).toEqual(['open: Changes 1 file', 'folded: Sub-agents none', 'folded: Details model, usage, tools, raw steps'])
  expect(within(fold('Changes')).getByText('farewell.py').parentElement).toHaveTextContent('farewell.py+1−1AppliedView diff')
  // what moved into Details is not on the page until it is opened
  expect(own).not.toHaveTextContent('38%')
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
})

test('the side panel is a short report card: who asked what, its report, its changes, its key numbers - and no story, no raw rows', () => {
  render(<Inspector state={done} selectedId="agent:r" onClose={() => {}} onOpenAgent={() => {}} />)
  const panel = screen.getByRole('complementary', { name: 'Inspector' })
  expect(within(panel).getByRole('button', { name: 'Open window' })).toBeInTheDocument()
  expect(within(panel).getByText(/^Asked by/).closest('p')).toHaveTextContent('Asked by you: Make it say goodbye instead.')
  expect(within(panel).getByRole('region', { name: 'Report' })).toHaveTextContent('The coder changed it: it says goodbye. Then it checked.')
  expect(panel.querySelector('.agent-report-clamp')).not.toBeNull() // (cut to a few lines; whole in its window)
  expect(folds(panel)).toEqual(['open: Changes 1 file'])
  expect(numbers(panel)).toEqual(['Did', '1 file changed · 2 tools · 0 commands · 1 step', 'Tokens', '380 in / 36 out'])
  expect(panel.querySelector('.agent-story')).toBeNull()
  expect(panel).not.toHaveTextContent(/Every step as recorded|Details|38%/)
})

test('while it works the panel says it has no report yet and what it is on now; unknown tokens are a dash', () => {
  const working = convState({
    ...done,
    runs: [run('r')],
    agents: [agent('r', 'running', { task: 'Go', report: null, input_tokens: null, output_tokens: null })],
    messages: [userMessage('r', 'go'), assistantMessage('a1', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'read_file', 'running', '{"path":"farewell.py"}', { message_id: 'a1' })],
    fileChanges: [],
  })
  render(<Inspector state={working} selectedId="agent:r" onClose={() => {}} />)
  const report = screen.getByRole('region', { name: 'Report' })
  expect(report).toHaveTextContent('No report yet — it writes one when its work is over.')
  expect(report).toHaveTextContent('Now: Looked around — read 1 file · now…')
  expect(screen.getByText('Tokens').nextElementSibling).toHaveTextContent(/^– in \/ – out$/)
})

test('a command that waits for the user is at the top of the panel and the last step of the window, the chat’s own card in both', () => {
  const waits = convState({
    runs: [run('r')],
    agents: [agent('r', 'running', { task: 'Measure it' })],
    messages: [assistantMessage('a1', 'r', 'To check it is not slower.')],
    toolCalls: [toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}', { message_id: 'a1' }), toolCall('2', 'r', 'run_command', 'pending', '{}', { message_id: 'a1' })],
    commands: [command('k1', 'r', { tool_call_id: '2', command: 'python measure.py', status: 'proposed', exit_code: null })],
  })
  const card = (c: { id: string; command: string }) => (
    <div key={c.id} role="group" aria-label="Run this command?">
      {c.command}
    </div>
  )
  render(<Inspector state={waits} selectedId="agent:r" onClose={() => {}} renderCommandApproval={card} />)
  const panel = screen.getByRole('complementary', { name: 'Inspector' })
  const asks = within(panel).getByRole('group', { name: 'Run this command?' })
  expect(asks).toHaveTextContent('python measure.py')
  expect(asks.compareDocumentPosition(within(panel).getByText(/^Asked by/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  cleanup()
  const { container } = render(<AgentWindow state={waits} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} renderCommandApproval={card} />)
  const last = container.querySelector('.agent-story > li:last-child') as HTMLElement
  expect(within(last).getByRole('heading', { level: 4 })).toHaveTextContent('Waits for you')
  expect(within(last).getByRole('group', { name: 'Run this command?' })).toHaveTextContent('python measure.py')
  // (the command is not a step of its own as well)
  expect(Array.from(container.querySelectorAll('.agent-story h4')).map(h => h.textContent)).toEqual(['Looked around', 'Waits for you'])
})

test('what is not known is not shown: no made-up line on top, and no count for what was not done', async () => {
  const waiting = convState({ runs: [run('r', 'queued')], agents: [agent('r', 'queued', { started_at: null })] })
  render(<AgentWindow state={waiting} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const own = screen.getByRole('region', { name: 'Agent window' })
  // no task, not started, no report, no tokens reported: no line for any
  expect(own.querySelector('.agent-numbers')).toBeNull()
  expect(own.querySelector('.agent-asked')).toBeEmptyDOMElement()
  expect(own).not.toHaveTextContent(/\d+%|0 tools|0 in/)
  expect(fold('Changes').querySelector('summary')).toHaveTextContent('Changes none')
  expect((await openAgentFold('Every step as recorded')).querySelector('summary')).toHaveTextContent('none')
})

test('what KOLONİ told it the same, several times in a row, is one step with ×N; its own words are never merged', async () => {
  const WORDS = 'Its source changed since this turn began.'
  const told = (id: string) => ({ ...assistantMessage(id, 'r', WORDS), role: 'memory' as const })
  const s = convState({
    runs: [run('r')],
    agents: [agent('r')],
    messages: [assistantMessage('a1', 'r', 'Same words.'), assistantMessage('a2', 'r', 'Same words.'), told('t1'), told('t2'), told('t3')],
  })
  render(<AgentWindow state={s} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const notes = screen.getAllByRole('note', { name: 'Told by KOLONİ about its memory' })
  expect(notes).toHaveLength(1)
  expect(notes[0]).toHaveTextContent('told by KOLONİ, about what it was given from memory ×3')
  expect(screen.getByRole('heading', { name: 'KOLONİ reminded it ×3' })).toBeInTheDocument()
  expect(screen.getAllByText('Same words.')).toHaveLength(2)
  expect((await openAgentFold('Every step as recorded')).querySelector('summary')).toHaveTextContent('3 steps')
})

test('K-inspector: a Reviewer’s report is on top and whole, its findings listed each with the role it went to, as its node counts them', async () => {
  const REPORT = '## Summary\nThe review found nothing blocking.\n\n## Findings\n- Name the magic number | kind: code | role: Coder | suggestion\n- Add a docstring | kind: docs | role: Coder | suggestion'
  const BRIEF = ['Review the tags feature.', ...Array.from({ length: 44 }, (_, i) => `Point ${i + 1}: check it.`)].join('\n')
  const s = convState({
    runs: [run('r', 'completed')],
    agents: [
      agent('r', 'completed', { id: 'lead' }),
      agent('r', 'completed', {
        id: 'rev', parent_agent_id: 'lead', role_name: 'Reviewer', name: 'Reviewer', depth: 1, task: BRIEF, report: REPORT,
        findings: [
          { what: 'Name the magic number', kind: 'code', role: 'Coder', blocking: false },
          { what: 'Add a docstring', kind: 'docs', role: 'Coder', blocking: false },
        ],
      }),
    ],
  })
  render(<AgentWindow state={s} agentId="rev" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const own = screen.getByRole('region', { name: 'Agent window' })
  const report = screen.getByText('Report').nextElementSibling as HTMLElement
  // the node's own line, then each finding with where it went; the report's prose whole, its Findings lines not twice
  expect(report).toHaveTextContent('2 suggestions → Coder ×2')
  expect(within(report).getAllByRole('listitem').map(li => li.textContent)).toEqual([
    'Name the magic number (code, suggestion) → Coder',
    'Add a docstring (docs, suggestion) → Coder',
  ])
  expect(within(report).getByRole('heading', { name: 'Summary' })).toBeInTheDocument()
  expect(report).toHaveTextContent('The review found nothing blocking.')
  expect(report).not.toHaveTextContent('kind: code')
  // who asked what, then the report (design A)
  const task = screen.getByText(/^Asked by/).closest('p') as HTMLElement
  expect(task.compareDocumentPosition(report) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(own).toContainElement(task)

  // the 45-line brief: its first line, the rest a click away
  expect(task).toHaveTextContent(/^Asked by Orchestrator: Review the tags feature\.▸ 45 lines$/)
  const unfold = within(task).getByRole('button', { name: '▸ 45 lines' })
  expect(unfold).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(unfold)
  expect(within(task).getByRole('button', { name: '▾ fold' })).toHaveAttribute('aria-expanded', 'true')
  expect(task).toHaveTextContent('Point 44: check it.')
})

test('the report’s Findings section is left out only where its findings are listed apart, and only that section', () => {
  expect(withoutFindings('Done.\n\n## Findings\n- x | kind: code | role: Coder | blocking')).toBe('Done.')
  expect(withoutFindings('Done.\n**Findings:**\n- x | kind: code\n## Checked\nran it')).toBe('Done.\n## Checked\nran it')
  expect(withoutFindings('No section here.\nThe findings were few.')).toBe('No section here.\nThe findings were few.')
  // it ends where the server's reading ends - at a Checked line or a fence - and one inside a fence is not it
  expect(withoutFindings('## Findings\n- x | kind: code\nChecked: ran pytest, 3 passed')).toBe('Checked: ran pytest, 3 passed')
  expect(withoutFindings('Findings:\n- x | kind: code\n```\nprint(1)\n```')).toBe('```\nprint(1)\n```')
  const fenced = 'Done.\n```\n## Findings\nin code\n```\n## Findings\n- x | kind: code'
  expect(withoutFindings(fenced)).toBe('Done.\n```\n## Findings\nin code\n```')
})

test('Did counts what it did itself: not its CLI sub-agent’s calls, a command that never ran, or a change thrown away', () => {
  const s = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed', { provider_name: 'Claude Code' })],
    messages: [userMessage('r', 'go'), assistantMessage('m1', 'r', 'Working.')],
    toolCalls: [
      toolCall('task', 'r', 'claude__Agent', 'succeeded', '{"description":"Look around","prompt":"Read hello.py"}', { message_id: 'm1', origin: 'cli' }),
      toolCall('in', 'r', 'claude__Read', 'succeeded', '{"file_path":"hello.py"}', { message_id: 'm1', origin: 'cli', parent_call_id: 'task' }),
      toolCall('w', 'r', 'write_file', 'succeeded', '{"path":"a.py"}', { message_id: 'm1' }),
      toolCall('c1', 'r', 'run_command', 'succeeded', '{"command":"ls"}', { message_id: 'm1' }),
      toolCall('c2', 'r', 'run_command', 'denied', '{"command":"rm x"}', { message_id: 'm1' }),
    ],
    commands: [command('k1', 'r', { tool_call_id: 'c1' }), command('k2', 'r', { tool_call_id: 'c2', status: 'rejected' })],
    fileChanges: [fileChange('f1', 'r', { tool_call_id: 'w', path: 'a.py' }), fileChange('f2', 'r', { path: 'b.py', status: 'discarded' })],
  })
  render(<AgentWindow state={s} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Did').nextElementSibling).toHaveTextContent('1 file changed · 2 tools · 1 command')
  // the thrown-away change is still listed, as what became of it
  expect(fold('Changes').querySelector('summary')).toHaveTextContent('Changes 2 files')
})

test('K-38b-sinirlar: steps that come while another window is in front are counted on its header, till the window is pressed', async () => {
  const props = { agentId: 'lead', onClose: () => {}, onOpenChange: () => {}, onSelectAgent: () => {} }
  const on = (shown: typeof state) => (
    <div className="stage">
      <section className="chat" />
      <AgentWindow state={shown} {...props} />
    </div>
  )
  const more = (n: number) => ({ ...state, messages: [...state.messages, ...Array.from({ length: n }, (_, i) => ({ ...assistantMessage(`n${i}`, 'r', `step ${i}`), agent_id: 'lead' }))] })
  const view = render(on(state))
  const window = screen.getByRole('region', { name: 'Agent window' })
  // Opened, it is in front: what comes is seen.
  view.rerender(on(more(1)))
  expect(window).not.toHaveTextContent(/\d+ new/)
  // The chat pressed: what comes now is new, and counted.
  toFront(view.container.querySelector('.chat')!)
  view.rerender(on(more(2)))
  expect(screen.getByText('1 new')).toBeInTheDocument()
  view.rerender(on(more(4)))
  expect(screen.getByText('3 new')).toBeInTheDocument()
  // Pressed again, it is seen.
  fireEvent.pointerDown(window)
  expect(window).not.toHaveTextContent(/\d+ new/)
})

test('Tell <name>… while it works: sent, and said so; what the server says where it could not hear; none once its work is over or where its CLI hears nothing (89d C)', async () => {
  useApp.setState({ providers: [{ name: 'Claude', kind: 'claude_cli' }, { name: 'Copilot', kind: 'copilot_cli' }] as Provider[] })
  const asked = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', asked)
  const show = (status: 'running' | 'completed', more: Partial<ReturnType<typeof agent>> = {}) =>
    render(
      <AgentWindow
        state={convState({ runs: [run('r', 'running')], agents: [agent('r', status, { id: 'coder', name: 'Coder', provider_name: 'Claude', provider_mode: 'native', ...more })] })}
        agentId="coder"
        onClose={() => {}}
        onOpenChange={() => {}}
        onSelectAgent={() => {}}
      />,
    )
  const tell = async () => {
    await userEvent.type(screen.getByRole('textbox', { name: 'Tell Coder' }), 'use blue')
    await userEvent.click(screen.getByRole('button', { name: 'Send to Coder' }))
  }
  show('running')
  expect(screen.getByPlaceholderText('Tell Coder…')).toBeInTheDocument()
  await tell()
  expect(asked).toHaveBeenCalledWith('/api/agents/coder/tell', expect.objectContaining({ method: 'POST', body: JSON.stringify({ words: 'use blue' }) }))
  expect(await screen.findByText('Sent to Coder while it works')).toHaveAttribute('role', 'status')
  expect(screen.getByRole('textbox', { name: 'Tell Coder' })).toHaveValue('')
  cleanup()
  // Its turn ended as it was sent: the server's why.
  asked.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Coder works on in its CLI, which hears nothing more' }), { status: 409 }))
  show('running')
  await tell()
  expect(await screen.findByRole('alert')).toHaveTextContent('Coder works on in its CLI, which hears nothing more')
  expect(screen.queryByText('Sent to Coder while it works')).toBeNull()
  cleanup()
  // Over, or a CLI that hears nothing more (Copilot's own session, agy's): no field.
  for (const [status, more] of [['completed', {}], ['running', { provider_name: 'Copilot' }], ['running', { provider_mode: 'reads' }]] as const) {
    show(status, more)
    expect(screen.queryByRole('textbox', { name: 'Tell Coder' })).toBeNull()
    cleanup()
  }
  vi.unstubAllGlobals()
  useApp.setState({ providers: [] })
})

test('an agent whose work is over has what waits for you on top of its window, once; its story’s last step points there', () => {
  const s = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed', { task: 'Go', report: 'Done.' })],
    questions: [question('q', 'r', { agent_id: 'r' })],
  })
  const card = (q: { id: string }) => (
    <div key={q.id} role="group" aria-label="It asks you">
      answer {q.id}
    </div>
  )
  const { container } = render(<AgentWindow state={s} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} renderQuestion={card} />)
  const asks = screen.getByRole('group', { name: 'It asks you' })
  expect(asks.compareDocumentPosition(screen.getByText(/^Asked by/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const last = container.querySelector('.agent-story > li:last-child') as HTMLElement
  expect(last).toHaveTextContent('Waits for youIts decision is on top of this window.')
})

test('a step’s rows opened while its command ran stay open once it has stopped; folded, they are not drawn', () => {
  const at = (status: 'running' | 'exited') =>
    convState({
      runs: [run('r')],
      agents: [agent('r', 'running')],
      messages: [assistantMessage('m1', 'r', '')],
      toolCalls: [toolCall('1', 'r', 'run_command', status === 'running' ? 'running' : 'succeeded', '{}', { message_id: 'm1' })],
      commands: [command('k1', 'r', { tool_call_id: '1', command: 'npm run build', status, exit_code: status === 'running' ? null : 0 })],
    })
  const { container, rerender } = render(<AgentWindow state={at('running')} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const fold = () => container.querySelector('.agent-phase-more') as HTMLElement
  expect(fold()).toHaveAttribute('open')
  rerender(<AgentWindow state={at('exited')} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(fold()).toHaveAttribute('open')
  expect(within(fold()).getByRole('button', { name: /npm run build/ })).toBeInTheDocument()
  fireEvent.click(within(fold()).getByText('What happened'))
  expect(fold()).not.toHaveAttribute('open')
})

test('a report the panel cuts says so with Show all, which opens it in place; a link in the cut part is out of the Tab order', async () => {
  const s = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { report: 'Long words.\n\n[the docs](https://example.com)' })] })
  const tall = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight')
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get() { return this.classList.contains('agent-report-clamp') ? 400 : 0 } })
  try {
    render(<Inspector state={s} selectedId="agent:r" onClose={() => {}} />)
    const link = screen.getByRole('link', { name: 'the docs' })
    expect(link).toHaveAttribute('tabindex', '-1') // (jsdom lays nothing out: every link is below the cut)
    await userEvent.click(screen.getByRole('button', { name: 'Show all' }))
    expect(screen.queryByRole('button', { name: 'Show all' })).not.toBeInTheDocument()
    expect(link).not.toHaveAttribute('tabindex')
    expect(link.closest('.agent-report-clamp')).toBeNull()
  } finally {
    if (tall) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', tall)
    else delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight
  }
})
