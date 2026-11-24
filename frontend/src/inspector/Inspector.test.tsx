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
import type { Attachment, Discussion, Provider } from '../api/types'
import { useApp } from '../state/store'
import { AgentWindow } from '../agents/AgentWindow'
import { Inspector } from './Inspector'

/** One of an agent's folds, by the words its line starts with. */
const fold = (name: string) =>
  screen.getByText(name, { selector: 'summary, summary *' }).closest('details') as HTMLElement

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
  expect(screen.getByText('Agent').nextElementSibling).toHaveTextContent('Orchestrator')
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
  const { container: panel } = render(<Inspector state={state} selectedId="agent:r" onClose={() => {}} />)
  // (Called as on its node: the Lead is the Orchestrator.)
  expect(panel.querySelector('.insp-title')).toHaveTextContent(/^Orchestrator$/)
  // what its provider did not report is said so, and no fill is made of it
  expect(screen.getByText('Tokens').nextElementSibling).toHaveTextContent(/^– in \/ 42 out$/)
  cleanup()
  const { container } = render(
    <AgentWindow state={state} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />,
  )
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
    agent('r', 'running', {
      id: 'kid',
      parent_agent_id: 'lead',
      role_name: 'Reviewer',
      task: 'Review hello.py carefully',
      depth: 1,
      tools: ['read_file', 'search'],
    }),
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
  expect(screen.getByText('Review hello.py carefully').closest('p')).toHaveTextContent(
    'Asked by Orchestrator: Review hello.py carefully',
  )
  cleanup()
  render(
    <AgentWindow state={family} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />,
  )
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
  render(
    <AgentWindow state={family} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={onSelect} />,
  )
  const kids = fold('Sub-agents')
  expect(kids.querySelector('summary')).toHaveTextContent('Sub-agents 1')
  await userEvent.click(within(kids).getByText('Sub-agents'))
  await userEvent.click(within(kids).getByRole('button', { name: /Reviewer/ }))
  expect(onSelect).toHaveBeenCalledWith('kid')
})

test('a proposed sub-agent can be decided from the inspector', () => {
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [
      agent('r', 'running', { id: 'lead' }),
      agent('r', 'proposed', { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', task: 't', depth: 1 }),
    ],
  })
  render(
    <Inspector
      state={state}
      selectedId="agent:kid"
      onClose={() => {}}
      renderSpawnApproval={a => <div>decide {a.role_name}</div>}
    />,
  )
  expect(screen.getByText('decide Coder')).toBeInTheDocument()
})

test('a role an agent asked for can be decided from that agent, and requests name their agent', () => {
  const state = convState({
    ...family,
    pendingRoles: [
      {
        tool_call_id: '9',
        run_id: 'r',
        agent_id: 'kid',
        name: 'Documenter',
        description: '',
        instructions: '',
        tools: ['read_file'],
      },
    ],
    commands: [command('k1', 'r', { agent_id: 'kid' })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'kid' })],
  })
  const { rerender } = render(
    <Inspector
      state={state}
      selectedId="agent:kid"
      onClose={() => {}}
      renderRoleApproval={r => <div>decide {r.name}</div>}
    />,
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
    questions: [
      question('q', 'r', { agent_id: 'kid' }),
      question('done', 'r', { agent_id: 'kid', status: 'answered', answer: 'x' }),
    ],
  })
  render(
    <Inspector
      state={state}
      selectedId="agent:kid"
      onClose={() => {}}
      renderQuestion={q => <div>answer {q.id}</div>}
    />,
  )
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
  const window = (s: typeof reading) => (
    <AgentWindow state={s} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />
  )
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
  render(
    <AgentWindow
      state={chained}
      agentId="coder-t3"
      onClose={() => {}}
      onOpenChange={() => {}}
      onSelectAgent={() => {}}
    />,
  )
  const earlier = fold('Earlier work')
  expect(earlier).not.toHaveAttribute('open')
  await userEvent.click(within(earlier).getByText('Earlier work'))
  expect(screen.getByRole('group', { name: `The ${sentAt(1)} message` })).toHaveTextContent('task 1')
  expect(screen.getByRole('group', { name: `The ${sentAt(1)} message` })).toHaveTextContent('report 1')
  expect(screen.getByRole('group', { name: `The ${sentAt(2)} message` })).toHaveTextContent('report 2')
  cleanup()
  const { rerender } = render(
    <Inspector state={chained} selectedId="agent:coder-t3" onClose={() => {}} onSelect={onSelect} />,
  )
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
  for (const close of [
    () => userEvent.keyboard('{Escape}'),
    () => userEvent.click(screen.getByRole('button', { name: 'Close inspector' })),
  ]) {
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
  expect(screen.getByRole('alert')).toHaveTextContent(
    'model server unreachable: refusedCheck that the model server is running, or pick another model.',
  )
})

test("an agent on Alibaba's plan key whose quota is used up says when it comes back, and where to see what is left", () => {
  const error = 'model server returned 429: Your token-plan quota has been exhausted.'
  const usedUp = convState({
    runs: [run('r', 'failed', { error })],
    agents: [agent('r', 'failed', { error, failure: 'rate_limited' })],
  })
  const alibaba = [
    { name: 'Local', plan: true, base_url: 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1' },
  ] as Provider[]
  render(<Inspector state={usedUp} providers={alibaba} selectedId="agent:r" onClose={() => {}} />)
  expect(screen.getByRole('alert')).toHaveTextContent(
    /Plan quota used up – it comes back at the start of its next subscription month, or with a usage bundle\./,
  )
  expect(screen.getByRole('link', { name: "See what is left in Alibaba's console" })).toHaveAttribute(
    'href',
    ALIBABA_CONSOLE,
  )
})

test('a decided sub-agent’s card goes once it starts, also from a renderer that keys it by the agent (no key twice in one list)', () => {
  const at = (status: 'proposed' | 'running') =>
    convState({
      runs: [run('r', 'running')],
      agents: [
        agent('r', 'running', { id: 'lead' }),
        agent('r', status, { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', task: 't', depth: 1 }),
      ],
    })
  const renderSpawnApproval = (a: { id: string; role_name: string }) => <div key={a.id}>decide {a.role_name}</div>
  const { rerender } = render(
    <Inspector
      state={at('proposed')}
      selectedId="agent:kid"
      onClose={() => {}}
      renderSpawnApproval={renderSpawnApproval}
    />,
  )
  expect(screen.getByText('decide Coder')).toBeInTheDocument()
  rerender(
    <Inspector
      state={at('running')}
      selectedId="agent:kid"
      onClose={() => {}}
      renderSpawnApproval={renderSpawnApproval}
    />,
  )
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
        <Inspector
          state={state}
          selectedId={selected}
          onClose={() => setSelected(null)}
          onOpenAgent={id => {
            onOpenAgent(id)
            setShown(id)
          }}
        />
      </>
    )
  }
  render(<Page />)
  await userEvent.click(screen.getByRole('button', { name: 'Open window' }))
  expect(onOpenAgent).toHaveBeenCalledWith('r')
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Agent window' })).toHaveFocus()
})

test('the Scout’s node opens what came of its request and why each one was dropped, in plain words', () => {
  const po = {
    provider_name: 'Fast',
    model_id: 'gpt-6-luna',
    heard: true,
    input_tokens: 3000,
    output_tokens: null,
    proposed: 1,
    dropped_more: 0,
    dropped: [
      { title: 'Rotate the keys', why: 'its source (30 characters) is not words said in the turn' },
      { title: 'Docs', why: "like the open task 'Write the docs'" },
    ],
  }
  render(
    <Inspector state={convState({ runs: [run('r', 'completed', { po })] })} selectedId="po:r" onClose={() => {}} />,
  )
  expect(screen.getByText('Scout')).toBeInTheDocument()
  expect(screen.getByText('Fast · gpt-6-luna · 3k tokens + –')).toBeInTheDocument()
  expect(screen.getByText('1 proposed · 2 dropped')).toBeInTheDocument()
  expect(screen.getByText('Rotate the keys:').parentElement).toHaveTextContent(
    'Rotate the keys: its source (30 characters) is not words said in the turn',
  )
  expect(screen.getByText('Docs:').parentElement).toHaveTextContent("Docs: like the open task 'Write the docs'")
  cleanup()
  // a turn it was not asked about: nothing to open
  const { container } = render(
    <Inspector state={convState({ runs: [run('r')] })} selectedId="po:r" onClose={() => {}} />,
  )
  expect(container).toBeEmptyDOMElement()
})

/** The inspector's head: its title and the line under it. */
const head = () => [
  document.querySelector('.insp-title')?.textContent,
  document.querySelector('.insp-sub')?.textContent,
]

test('a file you attached opens on its own, handed to whom; the box of a message’s files opens on them all, not a frame of a video', () => {
  const file = (id: string, over: Partial<Attachment> = {}): Attachment => ({
    id,
    conversation_id: 'c',
    message_id: 'u-r',
    frame_of: null,
    given_to: [],
    keep_in_project: false,
    kind: 'image',
    mime: 'image/png',
    name: `${id}.png`,
    shown_to: {},
    size: 10,
    summary: '',
    created_at: '2026-10-05T10:00:00Z',
    ...over,
  })
  const files = convState({
    runs: [run('r')],
    agents: [agent('r', 'running', { name: 'Coder' })],
    messages: [userMessage('r', 'look at these')],
    attachments: [file('a', { given_to: ['r'] }), file('b'), file('frame', { frame_of: 'b' })],
  })
  const { rerender } = render(<Inspector state={files} selectedId="attachment:a" onClose={() => {}} />)
  expect(head()).toEqual(['a.png', 'handed to Coder'])
  expect(screen.getByRole('img', { name: 'a.png' })).toBeInTheDocument()
  rerender(<Inspector state={files} selectedId="attachment:b" onClose={() => {}} />)
  expect(head()).toEqual(['b.png', 'attached by you'])
  rerender(<Inspector state={files} selectedId="files:r" onClose={() => {}} />)
  expect(head()).toEqual(['2 files', 'attached by you'])
  expect(Array.from(document.querySelectorAll('.att-mini'), mini => mini.textContent)).toEqual(['PNGa.png', 'PNGb.png'])
  // (one not there, or a turn with no request: nothing)
  rerender(<Inspector state={files} selectedId="attachment:gone" onClose={() => {}} />)
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).toBeNull()
  rerender(<Inspector state={files} selectedId="files:other" onClose={() => {}} />)
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).toBeNull()
})

test('a discussion opens its shared place from its button, when there is a way to; one not there opens nothing', async () => {
  const talk: Discussion = {
    id: 'd',
    run_id: 'r',
    agent_id: 'r',
    tool_call_id: '9',
    topic: 'Which way?',
    max_rounds: 3,
    round: 1,
    status: 'running',
    outcome: null,
    created_at: '2026-10-05T10:00:00Z',
    ended_at: null,
    members: [{ agent_id: 'r', status: 'in', opened_here: false }],
  }
  const talking = convState({
    runs: [run('r')],
    agents: [agent('r', 'running', { name: 'Coder' })],
    discussions: [talk],
  })
  const onOpenDiscussion = vi.fn()
  const { rerender } = render(
    <Inspector state={talking} selectedId="discussion:d" onClose={() => {}} onOpenDiscussion={onOpenDiscussion} />,
  )
  expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open discussion' }))
  expect(onOpenDiscussion).toHaveBeenCalledWith('d')
  rerender(<Inspector state={talking} selectedId="discussion:d" onClose={() => {}} />)
  expect(screen.queryByRole('button', { name: 'Open discussion' })).toBeNull()
  rerender(<Inspector state={talking} selectedId="discussion:gone" onClose={() => {}} />)
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).toBeNull()
})

test('a plan opens as it stands, from its own node and from over the Lead it was approved for; a turn with no plan opens nothing', () => {
  const plan = { text: '1. **read**\n2. write', status: 'approved' as const, model_id: 'big-model', strongest: true }
  const planned = convState({ runs: [run('p', 'completed', { plan_turn: true, plan }), run('w')] })
  const { rerender } = render(<Inspector state={planned} selectedId="plan:p" onClose={() => {}} />)
  expect(head()).toEqual(['Plan · approved', 'Planned by big-model · the team’s strongest model'])
  expect(screen.getByText('read').tagName).toBe('STRONG')
  rerender(<Inspector state={planned} selectedId="planned:p" onClose={() => {}} />)
  expect(head()).toEqual(['Plan · approved', 'Planned by big-model · the team’s strongest model'])
  rerender(<Inspector state={planned} selectedId="plan:w" onClose={() => {}} />)
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).toBeNull()
})

/** A CLI's own sub-agent (call 2), with a command and a file of its, beside the agent's own; a question of each. */
const withSub = convState({
  runs: [run('r')],
  agents: [agent('r', 'running', { name: 'Coder' })],
  toolCalls: [
    toolCall(
      '2',
      'r',
      'claude__Agent',
      'running',
      '{"description":"Look around","prompt":"x","subagent_type":"Explore"}',
      { origin: 'cli' },
    ),
    toolCall('4', 'r', 'run_command', 'succeeded', '{}', { origin: 'cli', parent_call_id: '2' }),
    toolCall('5', 'r', 'edit_file', 'succeeded', '{"path":"hello.py"}', { origin: 'cli', parent_call_id: '2' }),
    toolCall('6', 'r', 'run_command', 'failed', '{}'),
  ],
  commands: [
    command('k1', 'r', { origin: 'cli', tool_call_id: '4', command: 'python hello.py' }),
    command('k2', 'r', { tool_call_id: '6', command: 'git status' }),
  ],
  fileChanges: [
    fileChange('f1', 'r', { origin: 'cli', tool_call_id: '5', path: 'hello.py' }),
    fileChange('f2', 'r', { path: 'b.py' }),
  ],
  questions: [
    question('q1', 'r', { tool_call_id: '4' }),
    question('q2', 'r', { tool_call_id: '2' }),
    question('q3', 'r', { tool_call_id: '6' }),
    question('q4', 'r', { tool_call_id: '2', status: 'answered' }),
  ],
})

test('a sub-agent of the CLI’s own asks what waits on it and on its tools, opens its agent’s window; its commands and files are its own', async () => {
  const onOpenAgent = vi.fn()
  const { rerender } = render(
    <Inspector
      state={withSub}
      selectedId="subagent:2"
      onClose={() => {}}
      onOpenAgent={onOpenAgent}
      renderQuestion={q => <p key={q.id}>asks {q.id}</p>}
    />,
  )
  expect(head()).toEqual(['Look around', 'own sub-agent of Coder'])
  expect(screen.getAllByText(/^asks /).map(p => p.textContent)).toEqual(['asks q1', 'asks q2'])
  await userEvent.click(screen.getByRole('button', { name: 'Open window' }))
  expect(onOpenAgent).toHaveBeenCalledWith('r')
  rerender(<Inspector state={withSub} selectedId="commands:2" onClose={() => {}} />)
  expect(head()).toEqual(['Commands', '1 commands'])
  expect(screen.getByText('python hello.py')).toBeInTheDocument()
  rerender(<Inspector state={withSub} selectedId="commands:r" onClose={() => {}} />)
  expect(head()).toEqual(['Commands', '1 commands'])
  expect(screen.getByText('git status')).toBeInTheDocument()
  rerender(<Inspector state={withSub} selectedId="changes:2" onClose={() => {}} />)
  expect(head()).toEqual(['Files', '1 files'])
  expect(screen.getByText('hello.py')).toBeInTheDocument()
  rerender(<Inspector state={withSub} selectedId="changes:r" onClose={() => {}} />)
  expect(screen.getByText('b.py')).toBeInTheDocument()
  rerender(<Inspector state={withSub} selectedId="owntools:2" onClose={() => {}} />)
  expect(head()).toEqual(['Own tools', '1 calls'])
  // (without a way to open a window: no button)
  rerender(<Inspector state={withSub} selectedId="subagent:2" onClose={() => {}} />)
  expect(screen.queryByRole('button', { name: 'Open window' })).toBeNull()
})

test('one command opens with what it is, its card while it waits and no "No output" then; one file says what kind of change by whom', () => {
  const waits = command('k', 'r', { origin: 'cli', status: 'proposed', started_at: null, ended_at: null, cwd: null })
  const state = convState({
    runs: [run('r')],
    agents: [agent('r', 'running', { name: 'Coder' })],
    commands: [waits],
    fileChanges: [
      fileChange('new', 'r', { origin: 'cli', kind: 'create', path: 'src/new.py' }),
      fileChange('gone', 'r', { kind: 'delete', path: 'old.py' }),
    ],
  })
  const facts = () => Array.from(document.querySelectorAll('.facts dd'), dd => dd.textContent)
  const { rerender } = render(
    <Inspector
      state={state}
      selectedId="command:k"
      onClose={() => {}}
      renderCommandApproval={c => <p>decide {c.id}</p>}
    />,
  )
  expect(facts()).toEqual([
    'waits for you',
    'Coder',
    'the CLI itself, with a tool of its own',
    'not known',
    'This machine',
    '—',
    '120s',
  ])
  expect(screen.getByText('decide k')).toBeInTheDocument()
  expect(screen.queryByText('No output.')).toBeNull()
  rerender(<Inspector state={state} selectedId="file:new" onClose={() => {}} />)
  expect(head()).toEqual(['new.py', 'src/new.py'])
  expect(facts()).toEqual(['Coder', 'the CLI itself, with a tool of its own', 'new file', 'Applied'])
  rerender(<Inspector state={state} selectedId="file:gone" onClose={() => {}} />)
  expect(facts()).toEqual(['Coder', 'KOLONİ', 'deleted file', 'Applied'])
})
