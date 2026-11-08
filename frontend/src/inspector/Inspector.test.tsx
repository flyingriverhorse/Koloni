import { act, cleanup, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import {
  agent,
  assistantMessage,
  command,
  convState,
  fileChange,
  question,
  run,
  openAgentFold,
  toolCall,
  userMessage,
} from '../test-fixtures'
import { sentAt, topicOf } from '../canvas/thread.fixtures'
import { ALIBABA_CONSOLE } from '../agents/failure'
import type { Provider } from '../api/types'
import { useApp } from '../state/store'
import { AgentWindow } from '../agents/AgentWindow'
import { Inspector } from './Inspector'

/** One of an agent's folds, by the words its line starts with. */
const fold = (name: string) => screen.getByText(name, { selector: 'summary, summary *' }).closest('details') as HTMLElement

const state = convState({
  runs: [run('r', 'completed', { input_tokens: null, output_tokens: 42 })],
  agents: [agent('r', 'completed', { output_tokens: 42 })],
  messages: [userMessage('r', 'what does a.py do?'), assistantMessage('a', 'r', 'It prints **hi**.')],
  toolCalls: [
    toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}', { result: "     1\tprint('hi')" }),
    toolCall('2', 'r', 'search', 'failed', '{"pattern":"("}', { result: 'error: invalid regular expression' }),
  ],
})

test('with nothing selected the inspector takes no room', () => {
  const { container } = render(<Inspector state={state} selectedId={null} onClose={() => {}} />)
  expect(container).toBeEmptyDOMElement()
})

test('the tools node lists each call and reveals its result on click', async () => {
  render(<Inspector state={state} selectedId="tools:r" onClose={() => {}} />)
  expect(screen.getByText('read_file a.py')).toBeInTheDocument()
  expect(screen.getByText('search "("')).toBeInTheDocument()
  expect(screen.queryByText(/print\('hi'\)/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /read_file a\.py/ }))
  expect(screen.getByText(/print\('hi'\)/)).toBeInTheDocument()
})

test('a card of many commands lists the agent’s, each with its output on click', async () => {
  const many = convState({
    runs: [run('r')],
    agents: [agent('r'), agent('r', 'running', { id: 'kid', parent_agent_id: 'r', depth: 1 })],
    commands: [
      command('k1', 'r', { command: 'git status', output: 'clean\n' }),
      command('k2', 'r', { command: 'python train.py', exit_code: 1 }),
      command('k3', 'r', { agent_id: 'kid', command: 'npm test' }),
    ],
  })
  render(<Inspector state={many} selectedId="commands:r" onClose={() => {}} />)
  expect(screen.getByText('2 commands')).toBeInTheDocument()
  expect(screen.getByText('python train.py')).toBeInTheDocument()
  expect(screen.queryByText('npm test')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /git status/ }))
  expect(screen.getByText(/clean/)).toBeInTheDocument()
})

test('a card of many files lists the agent’s that wait for nobody, each opened on its own', async () => {
  const onSelect = vi.fn()
  const many = convState({
    runs: [run('r')],
    agents: [agent('r'), agent('r', 'running', { id: 'kid', parent_agent_id: 'r', depth: 1 })],
    fileChanges: [
      fileChange('f1', 'r', { path: 'src/a.py' }),
      fileChange('f2', 'r', { path: 'src/b.py', status: 'in_copy' }),
      fileChange('f3', 'r', { path: 'src/c.py', status: 'proposed' }),
      fileChange('f4', 'r', { agent_id: 'kid', path: 'src/d.py' }),
    ],
  })
  render(<Inspector state={many} selectedId="changes:r" onClose={() => {}} onSelect={onSelect} />)
  expect(screen.getByText('2 files')).toBeInTheDocument()
  expect(screen.queryByText('src/c.py')).not.toBeInTheDocument()
  expect(screen.queryByText('src/d.py')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open src/b.py' }))
  expect(onSelect).toHaveBeenCalledWith('file:f2')
})

test('one call, picked from a tool node’s list, shows what it was given and what came back', () => {
  const { rerender, container } = render(<Inspector state={state} selectedId="call:2" onClose={() => {}} />)
  const inspector = screen.getByRole('complementary', { name: 'Inspector' })
  expect(inspector).toHaveTextContent('search "("')
  expect(screen.getByText('Status').nextElementSibling).toHaveTextContent('failed')
  expect(screen.getByText('Agent').nextElementSibling).toHaveTextContent('Lead')
  expect(screen.getByText('Run by').nextElementSibling).toHaveTextContent('KOLONİ')
  // open at once: nothing more to click
  expect(screen.getByText('{"pattern":"("}')).toBeInTheDocument()
  expect(screen.getByText('error: invalid regular expression')).toBeInTheDocument()
  expect(screen.queryByText(/print\('hi'\)/)).not.toBeInTheDocument()
  // a tool of the CLI's own says so; one that has not returned says that
  const own = convState({
    ...state,
    toolCalls: [toolCall('9', 'r', 'claude__Read', 'running', '{"file_path":"a.py"}', { origin: 'cli' })],
  })
  rerender(<Inspector state={own} selectedId="call:9" onClose={() => {}} />)
  expect(screen.getByText('Run by').nextElementSibling).toHaveTextContent('the CLI itself, with a tool of its own')
  expect(screen.getByText('(no result yet)')).toBeInTheDocument()
  rerender(<Inspector state={state} selectedId="call:gone" onClose={() => {}} />)
  expect(container).toBeEmptyDOMElement()
})

test('the agent node shows its key numbers, an unknown count a dash; its window has the rest, its raw steps drawn once opened', async () => {
  render(<Inspector state={state} selectedId="agent:r" onClose={() => {}} />)
  // what its provider did not report is said so, and no fill is made of it
  expect(screen.getByText('Tokens').nextElementSibling).toHaveTextContent(/^– in \/ 42 out$/)
  cleanup()
  const { container } = render(<AgentWindow state={state} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('Context').nextElementSibling).toHaveTextContent(/^unknown in \/ 42 out$/)
  expect(screen.getByText('Model').nextElementSibling).toHaveTextContent('qwen')
  // its words are in its story; its raw steps are drawn once they are opened
  expect(container.querySelector('.agent-story')).toHaveTextContent('It prints hi.')
  expect(container.querySelector('.agent-feed-step')).toBeNull()
  await openAgentFold('Every step as recorded')
  expect(container.querySelector('.agent-feed-step')).toHaveTextContent('It prints hi.')
})

test('the request node shows the full message and close reports back', async () => {
  const onClose = vi.fn()
  render(<Inspector state={state} selectedId="request:r" onClose={onClose} />)
  expect(screen.getByText('what does a.py do?')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close inspector' }))
  expect(onClose).toHaveBeenCalled()
})

test('a selection that no longer exists shows nothing', () => {
  const { container } = render(<Inspector state={state} selectedId="agent:gone" onClose={() => {}} />)
  expect(container).toBeEmptyDOMElement()
})

const family = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'waiting', { id: 'lead' }),
    agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', task: 'Review hello.py carefully', depth: 1, tools: ['read_file', 'search'] }),
  ],
  messages: [
    userMessage('r', 'x'),
    { ...assistantMessage('m1', 'r', 'lead words'), agent_id: 'lead' },
    { ...assistantMessage('m2', 'r', 'reviewer words'), agent_id: 'kid' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Reviewer"}', { agent_id: 'lead', message_id: 'm1' }),
    toolCall('2', 'r', 'read_file', 'succeeded', '{"path":"hello.py"}', { agent_id: 'kid', message_id: 'm2' }),
  ],
})

test('a sub-agent shows its role and who asked it what; its window its tools and only its own conversation', async () => {
  render(<Inspector state={family} selectedId="agent:kid" onClose={() => {}} />)
  expect(screen.getByText('Reviewer')).toBeInTheDocument()
  expect(screen.getByText('Review hello.py carefully').closest('p')).toHaveTextContent('Asked by Orchestrator: Review hello.py carefully')
  cleanup()
  render(<AgentWindow state={family} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('search')).toBeInTheDocument()
  expect(screen.getByText('Depth').nextElementSibling).toHaveTextContent('1')
  const steps = await openAgentFold('Every step as recorded')
  expect(within(steps).getByText('reviewer words')).toBeInTheDocument()
  expect(within(steps).getByText('read_file hello.py')).toBeInTheDocument()
  expect(screen.queryByText('lead words')).not.toBeInTheDocument()
})

test('an agent’s window lists its sub-agents and selecting one reports it', async () => {
  const onSelect = vi.fn()
  render(<AgentWindow state={family} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={onSelect} />)
  const kids = fold('Sub-agents')
  expect(kids.querySelector('summary')).toHaveTextContent('Sub-agents 1')
  await userEvent.click(within(kids).getByText('Sub-agents'))
  await userEvent.click(within(kids).getByRole('button', { name: /Reviewer/ }))
  expect(onSelect).toHaveBeenCalledWith('kid')
})

test('a proposed sub-agent can be decided from the inspector', () => {
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { id: 'lead' }), agent('r', 'proposed', { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', task: 't', depth: 1 })],
  })
  render(
    <Inspector state={state} selectedId="agent:kid" onClose={() => {}} renderSpawnApproval={a => <div>decide {a.role_name}</div>} />,
  )
  expect(screen.getByText('decide Coder')).toBeInTheDocument()
})

test('a role an agent asked for can be decided from that agent, and requests name their agent', () => {
  const state = convState({
    ...family,
    pendingRoles: [{ tool_call_id: '9', run_id: 'r', agent_id: 'kid', name: 'Documenter', description: '', instructions: '', tools: ['read_file'] }],
    commands: [command('k1', 'r', { agent_id: 'kid' })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'kid' })],
  })
  const { rerender } = render(
    <Inspector state={state} selectedId="agent:kid" onClose={() => {}} renderRoleApproval={r => <div>decide {r.name}</div>} />,
  )
  expect(screen.getByText('decide Documenter')).toBeInTheDocument()
  rerender(<Inspector state={state} selectedId="command:k1" onClose={() => {}} />)
  expect(screen.getByText('Agent').nextElementSibling).toHaveTextContent('Reviewer')
  rerender(<Inspector state={state} selectedId="file:f1" onClose={() => {}} />)
  expect(screen.getByText('Agent').nextElementSibling).toHaveTextContent('Reviewer')
})

test('an agent’s open question can be answered from the inspector', () => {
  const state = convState({
    ...family,
    questions: [question('q', 'r', { agent_id: 'kid' }), question('done', 'r', { agent_id: 'kid', status: 'answered', answer: 'x' })],
  })
  render(<Inspector state={state} selectedId="agent:kid" onClose={() => {}} renderQuestion={q => <div>answer {q.id}</div>} />)
  expect(screen.getByText('answer q')).toBeInTheDocument()
  expect(screen.queryByText('answer done')).not.toBeInTheDocument()
})

test('an agent’s details name its provider and its own model', async () => {
  const state = convState({
    runs: [run('r', 'completed', { model_id: 'claude-sonnet' })],
    agents: [agent('r', 'completed', { provider_name: 'Local', model_id: 'qwen' })],
  })
  render(<AgentWindow state={state} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  expect(screen.getByText('Provider').nextElementSibling).toHaveTextContent('Local')
  expect(screen.getByText('Model').nextElementSibling).toHaveTextContent('qwen')
})

test('a sub-agent whose model is not known yet does not borrow its lead’s', () => {
  const state = convState({
    runs: [run('r', 'waiting_approval', { model_id: 'claude-sonnet' })],
    agents: [
      agent('r', 'running', { id: 'lead', model_id: 'claude-sonnet' }),
      agent('r', 'proposed', { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, model_id: null }),
    ],
  })
  render(<Inspector state={state} selectedId="agent:kid" onClose={() => {}} />)
  expect(screen.queryByText('claude-sonnet')).not.toBeInTheDocument()
})

test('an agent on a CLI that only reads: its role’s write and command tools are said not to apply', async () => {
  const reading = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { provider_name: 'agy', provider_mode: 'reads' })],
    messages: [userMessage('r', 'look')],
  })
  render(<Inspector state={reading} selectedId="agent:r" onClose={() => {}} />)
  // said on the panel without a click; why, under its window's Details
  expect(screen.getByText('reads only', { selector: '.tag' })).toBeVisible()
  cleanup()
  const window = (s: typeof reading) => <AgentWindow state={s} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />
  const { rerender } = render(window(reading))
  expect(screen.getByText('reads only', { selector: '.tag' })).toBeVisible()
  await openAgentFold('Details')
  expect(screen.getByRole('note')).toHaveTextContent(
    'Reads only: on this provider it works with the CLI’s own tools, and the CLI was started without leave to write or run; your own agy settings can allow more. The tools of its role, listed above, do not apply.',
  )
  // a change of its own on record: the note says that something got through
  rerender(window({ ...reading, fileChanges: [fileChange('f1', 'r', { origin: 'cli' })] }))
  expect(screen.getByRole('note')).toHaveTextContent(
    'Reads only (your agy settings let something through): on this provider it works with the CLI’s own tools',
  )
  rerender(window(state))
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test('an agent that goes on from an earlier turn says so on its task’s line, its earlier work folded in its window; one a later agent went on from leads there', async () => {
  const onSelect = vi.fn()
  const chained = topicOf(3)
  render(<AgentWindow state={chained} agentId="coder-t3" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const earlier = fold('Earlier work')
  expect(earlier).not.toHaveAttribute('open')
  await userEvent.click(within(earlier).getByText('Earlier work'))
  expect(screen.getByRole('group', { name: `The ${sentAt(1)} message` })).toHaveTextContent('task 1')
  expect(screen.getByRole('group', { name: `The ${sentAt(1)} message` })).toHaveTextContent('report 1')
  expect(screen.getByRole('group', { name: `The ${sentAt(2)} message` })).toHaveTextContent('report 2')
  cleanup()
  const { rerender } = render(<Inspector state={chained} selectedId="agent:coder-t3" onClose={() => {}} onSelect={onSelect} />)
  expect(screen.getByText(/^Asked by/).closest('p')).toHaveTextContent(`(continues from the ${sentAt(2)} message)`)
  expect(screen.queryByRole('button', { name: /^went on in/ })).not.toBeInTheDocument()

  rerender(<Inspector state={chained} selectedId="agent:coder-t1" onClose={() => {}} onSelect={onSelect} />)
  expect(screen.queryByText('Earlier work')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: `went on in the ${sentAt(2)} message` }))
  expect(onSelect).toHaveBeenCalledWith('agent:coder-t2')
  // a lead says neither: the topic's turns are that
  rerender(<Inspector state={chained} selectedId="agent:t2" onClose={() => {}} onSelect={onSelect} />)
  expect(screen.queryByText(/continues from/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^went on in/ })).not.toBeInTheDocument()
  expect(screen.queryByText('Earlier work')).not.toBeInTheDocument()
})

test('Esc closes the inspector, like its close button, and the focus goes back to what opened it', async () => {
  function Opened() {
    const [selected, setSelected] = useState<string | null>(null)
    return (
      <>
        <button type="button" onClick={() => setSelected('agent:r')}>
          the agent's node
        </button>
        <Inspector state={state} selectedId={selected} onClose={() => setSelected(null)} />
      </>
    )
  }
  render(<Opened />)
  const node = screen.getByRole('button', { name: "the agent's node" })
  for (const close of [() => userEvent.keyboard('{Escape}'), () => userEvent.click(screen.getByRole('button', { name: 'Close inspector' }))]) {
    await userEvent.click(node)
    const inspector = screen.getByRole('complementary', { name: 'Inspector' })
    // reached by Tab from what opened it
    await userEvent.tab()
    expect(inspector).toContainElement(document.activeElement as HTMLElement)
    await close()
    expect(screen.queryByRole('complementary', { name: 'Inspector' })).not.toBeInTheDocument()
    expect(node).toHaveFocus()
  }
})

test('Esc closes the inspector from wherever the focus is - the node that opened it - but not from a layer with an Esc of its own', async () => {
  function Opened() {
    const [selected, setSelected] = useState<string | null>(null)
    return (
      <>
        <button type="button" onClick={() => setSelected('agent:r')}>
          the agent's node
        </button>
        <section className="chat" aria-label="Chat">
          <input aria-label="Message" />
        </section>
        <Inspector state={state} selectedId={selected} onClose={() => setSelected(null)} />
      </>
    )
  }
  render(<Opened />)
  const node = screen.getByRole('button', { name: "the agent's node" })
  await userEvent.click(node)
  expect(node).toHaveFocus()
  // in the chat, Esc is the chat's
  await userEvent.click(screen.getByLabelText('Message'))
  await userEvent.keyboard('{Escape}')
  expect(screen.getByRole('complementary', { name: 'Inspector' })).toBeInTheDocument()
  // on the node that opened it, Esc closes it, and the focus stays there
  node.focus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).not.toBeInTheDocument()
  expect(node).toHaveFocus()
})

test('an agent that failed says, under its error, the one step to take', () => {
  const down = convState({
    runs: [run('r', 'failed', { error: 'model server unreachable: refused' })],
    agents: [agent('r', 'failed', { error: 'model server unreachable: refused' })],
  })
  render(<Inspector state={down} selectedId="agent:r" onClose={() => {}} />)
  expect(screen.getByRole('alert')).toHaveTextContent('model server unreachable: refusedCheck that the model server is running, or pick another model.')
})

test("an agent on Alibaba's plan key whose quota is used up says when it comes back, and where to see what is left", () => {
  const error = 'model server returned 429: Your token-plan quota has been exhausted.'
  const usedUp = convState({ runs: [run('r', 'failed', { error })], agents: [agent('r', 'failed', { error, failure: 'rate_limited' })] })
  const alibaba = [{ name: 'Local', plan: true, base_url: 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1' }] as Provider[]
  render(<Inspector state={usedUp} providers={alibaba} selectedId="agent:r" onClose={() => {}} />)
  expect(screen.getByRole('alert')).toHaveTextContent(/Plan quota used up – it comes back at the start of its next subscription month, or with a usage bundle\./)
  expect(screen.getByRole('link', { name: "See what is left in Alibaba's console" })).toHaveAttribute('href', ALIBABA_CONSOLE)
})

test('a decided sub-agent’s card goes once it starts, also from a renderer that keys it by the agent (no key twice in one list)', () => {
  const at = (status: 'proposed' | 'running') =>
    convState({
      runs: [run('r', 'running')],
      agents: [agent('r', 'running', { id: 'lead' }), agent('r', status, { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', task: 't', depth: 1 })],
    })
  const renderSpawnApproval = (a: { id: string; role_name: string }) => <div key={a.id}>decide {a.role_name}</div>
  const { rerender } = render(<Inspector state={at('proposed')} selectedId="agent:kid" onClose={() => {}} renderSpawnApproval={renderSpawnApproval} />)
  expect(screen.getByText('decide Coder')).toBeInTheDocument()
  rerender(<Inspector state={at('running')} selectedId="agent:kid" onClose={() => {}} renderSpawnApproval={renderSpawnApproval} />)
  expect(screen.queryByText('decide Coder')).not.toBeInTheDocument()
})

test('R160: while its own window is open the inspector does not show the agent a second time, and does again once it is closed', async () => {
  const onOpenAgent = vi.fn((id: string) => useApp.getState().openAgentWindow(id))
  try {
    render(<Inspector state={state} selectedId="agent:r" onClose={() => {}} onOpenAgent={onOpenAgent} />)
    const inspector = screen.getByRole('complementary', { name: 'Inspector' })
    expect(within(inspector).getByText('Did')).toBeInTheDocument()
    await userEvent.click(within(inspector).getByRole('button', { name: 'Open window' }))
    expect(onOpenAgent).toHaveBeenCalledWith('r')
    // (Here the panel stays, as when it is picked again: its name and Open window stay; what the window shows is not drawn twice.)
    expect(within(inspector).getByText('Shown in its window.')).toBeInTheDocument()
    expect(within(inspector).queryByText('Did')).not.toBeInTheDocument()
    act(() => useApp.getState().closeAgentWindow())
    expect(within(inspector).getByText('Did')).toBeInTheDocument()
  } finally {
    useApp.setState({ agentWindowId: null, agentWindowRaw: false })
  }
})

test('Open window opens the agent’s window, closes the panel and hands the window the focus', async () => {
  const onOpenAgent = vi.fn()
  function Page() {
    const [selected, setSelected] = useState<string | null>('agent:r')
    const [shown, setShown] = useState<string | null>(null)
    return (
      <>
        {shown && <section className="agent-window" tabIndex={-1} aria-label="Agent window" />}
        <Inspector state={state} selectedId={selected} onClose={() => setSelected(null)} onOpenAgent={id => { onOpenAgent(id); setShown(id) }} />
      </>
    )
  }
  render(<Page />)
  await userEvent.click(screen.getByRole('button', { name: 'Open window' }))
  expect(onOpenAgent).toHaveBeenCalledWith('r')
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Agent window' })).toHaveFocus()
})

test('the Assistant PO’s node opens what came of its request and why each one was dropped, in plain words', () => {
  const po = {
    provider_name: 'Fast', model_id: 'gpt-6-luna', heard: true, input_tokens: 3000, output_tokens: null, proposed: 1, dropped_more: 0,
    dropped: [{ title: 'Rotate the keys', why: 'its source (30 characters) is not words said in the turn' }, { title: 'Docs', why: "like the open task 'Write the docs'" }],
  }
  render(<Inspector state={convState({ runs: [run('r', 'completed', { po })] })} selectedId="po:r" onClose={() => {}} />)
  expect(screen.getByText('Assistant PO')).toBeInTheDocument()
  expect(screen.getByText('Fast · gpt-6-luna · 3k tokens + –')).toBeInTheDocument()
  expect(screen.getByText('1 proposed · 2 dropped')).toBeInTheDocument()
  expect(screen.getByText('Rotate the keys:').parentElement).toHaveTextContent('Rotate the keys: its source (30 characters) is not words said in the turn')
  expect(screen.getByText('Docs:').parentElement).toHaveTextContent("Docs: like the open task 'Write the docs'")
  cleanup()
  // a turn it was not asked about: nothing to open
  const { container } = render(<Inspector state={convState({ runs: [run('r')] })} selectedId="po:r" onClose={() => {}} />)
  expect(container).toBeEmptyDOMElement()
})
