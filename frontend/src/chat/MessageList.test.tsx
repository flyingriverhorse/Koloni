import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Attachment, Message, Provider, Role } from '../api/types'
import {
  agent,
  assistantMessage,
  command,
  convState,
  fileChange,
  question,
  run,
  toolCall,
  topic,
  userMessage,
} from '../test-fixtures'
import { ALIBABA_CONSOLE } from '../agents/failure'
import { when } from '../canvas/turns'
import { MessageList } from './MessageList'

const handlers = {
  onRemoveQueued: vi.fn(),
  onOpenChange: vi.fn(),
  onDecide: vi.fn(),
  onDecideCommand: vi.fn(),
}

test('turns are shown in order even when a queued message arrived mid-turn', () => {
  // Arrival order: first request, the queued request, then the first turn's reply.
  const messages: Message[] = [
    userMessage('a', 'first request'),
    userMessage('b', 'queued request'),
    assistantMessage('m1', 'a', 'first reply'),
  ]
  const { container } = render(
    <MessageList
      {...handlers}
      state={convState({ runs: [run('a', 'completed'), run('b', 'running')], messages })}
    />,
  )
  const text = container.textContent ?? ''
  expect(text.indexOf('first request')).toBeLessThan(text.indexOf('first reply'))
  expect(text.indexOf('first reply')).toBeLessThan(text.indexOf('queued request'))
})

test('KOLONİ’s line after the Lead’s answer stands above it: the answer stays the turn’s last word, its end line under it', () => {
  // R178 (live): "Tester was not opened this turn." came last, under the summary, and was missed.
  const note: Message = { ...assistantMessage('k', 'r', 'Tester was not opened this turn.'), role: 'koloni', agent_id: null }
  const { container } = render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('r', 'failed', { error: 'step_limit' })],
        messages: [userMessage('r', 'do it'), assistantMessage('m', 'r', 'Summary: Tester checked it'), note],
      })}
    />,
  )
  const text = container.textContent ?? ''
  expect(text.indexOf('do it')).toBeLessThan(text.indexOf('Tester was not opened'))
  expect(text.indexOf('Tester was not opened')).toBeLessThan(text.indexOf('Summary: Tester checked it'))
  expect(text.indexOf('Summary: Tester checked it')).toBeLessThan(text.indexOf('Stopped at its step limit'))
})

test('B-205: where the turn’s work is stands under the Lead’s answer, as KOLONİ’s - not the model’s words', () => {
  const landed: Message = {
    ...assistantMessage('l', 'r', 'Not in the project yet: a.py waits in Ready for you - Take in to apply it.'),
    role: 'landed',
    agent_id: null,
  }
  const { container } = render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('r', 'completed')],
        messages: [userMessage('r', 'fix it'), assistantMessage('m', 'r', 'Fixed, tests pass.'), landed],
      })}
    />,
  )
  const note = screen.getByRole('note')
  expect(note).toHaveTextContent('KOLONİ: Not in the project yet: a.py waits in Ready for you')
  expect(note).not.toHaveClass('msg-assistant')
  const text = container.textContent ?? ''
  expect(text.indexOf('Fixed, tests pass.')).toBeLessThan(text.indexOf('Not in the project yet'))
})

test('a queued message is labelled and can be removed', async () => {
  const onRemoveQueued = vi.fn()
  render(
    <MessageList
      {...handlers}
      onRemoveQueued={onRemoveQueued}
      state={convState({
        runs: [run('a'), run('q', 'queued')],
        messages: [userMessage('a', 'first'), userMessage('q', 'later')],
      })}
    />,
  )
  expect(screen.getByText('Queued')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
  expect(onRemoveQueued).toHaveBeenCalledWith('q')
})

test('a message removed from the queue stays visible and says so', () => {
  render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('q', 'cancelled', { started_at: null })],
        messages: [userMessage('q', 'never mind')],
      })}
    />,
  )
  expect(screen.getByText('Removed from queue')).toBeInTheDocument()
  expect(screen.queryByText('Stopped')).not.toBeInTheDocument()
})

test.each([
  [run('r', 'failed', { error: 'model server unreachable: refused' }), 'Run failed', 'model server unreachable: refused'],
  [run('r', 'failed', { error: 'step_limit' }), 'Stopped at its step limit', null],
  [run('r', 'cancelled'), 'Stopped', null],
  [run('r', 'interrupted'), 'Interrupted by a server restart', 'Send a message to continue.'],
])('a turn that did not complete says why, as a card that only tells', (endedRun, title, said) => {
  render(
    <MessageList
      {...handlers}
      state={convState({ runs: [endedRun], messages: [userMessage('r', 'do it')] })}
    />,
  )
  const card = screen.getByText(title).closest('.cmd-approval')
  expect(card).toHaveClass('card-tell')
  if (said) expect(card).toHaveTextContent(`${title}${said}`)
})

test('a failed turn says the one thing to do about it under why it failed; where nothing is known to help, nothing', () => {
  const failed = (error: string, lead = agent('r', 'failed')) =>
    render(<MessageList {...handlers} state={convState({ runs: [run('r', 'failed', { error })], messages: [userMessage('r', 'do it')], agents: [lead] })} />)
  const { unmount } = failed('model server unreachable: refused')
  expect(screen.getByRole('alert')).toHaveTextContent('Run failedmodel server unreachable: refusedCheck that the model server is running, or pick another model.')
  unmount()
  failed('model server returned 429', agent('r', 'failed', { failure: 'rate_limited' }))
  expect(screen.getByRole('alert')).toHaveTextContent(/Wait a while, or pick another model\.$/)
  cleanup()
  // Alibaba's plan key with its quota used up: when it comes back, and where to see what is left.
  const usedUp = 'model server returned 429: Your token-plan quota has been exhausted.'
  const alibaba = [{ name: 'Local', plan: true, base_url: 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1' }] as Provider[]
  render(<MessageList {...handlers} providers={alibaba} state={convState({ runs: [run('r', 'failed', { error: usedUp })], messages: [userMessage('r', 'do it')], agents: [agent('r', 'failed', { failure: 'rate_limited' })] })} />)
  expect(screen.getByRole('alert')).toHaveTextContent(/Plan quota used up – it comes back at the start of its next subscription month, or with a usage bundle\./)
  expect(screen.getByRole('link', { name: "See what is left in Alibaba's console" })).toHaveAttribute('href', ALIBABA_CONSOLE)
  cleanup()
  failed('something nobody knows')
  expect(screen.getByRole('alert')).toHaveTextContent(/^Run failedsomething nobody knows$/)
})

test('a turn whose lead ran out of credit says so in plain words, before the provider’s own', () => {
  const error = 'model server returned 400: Your credit balance is too low'
  render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('r', 'failed', { error })],
        agents: [agent('r', 'failed', { provider_name: 'Paid', failure: 'credits_exhausted', error })],
        messages: [userMessage('r', 'do it')],
      })}
    />,
  )
  expect(screen.getByText(`Paid: out of credits. ${error}`)).toBeInTheDocument()
})

test('tool calls sit under the step that made them; a step with only tools shows no empty bubble', () => {
  const step = { ...assistantMessage('m', 'r', ''), id: 'm' }
  const { container } = render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('r')],
        messages: [userMessage('r', 'look'), step],
        toolCalls: [toolCall('1', 'r', 'read_file', 'running', '{"path":"a.py"}')],
      })}
    />,
  )
  expect(screen.getByText('read_file a.py')).toBeInTheDocument()
  expect(container.querySelector('.msg-assistant')).toBeNull()
})

test('thinking is shown under the active turn only', () => {
  render(
    <MessageList
      {...handlers}
      state={convState({
        runs: [run('r')],
        messages: [userMessage('r', 'hm')],
        thinkingRunId: 'r',
      })}
    />,
  )
  expect(screen.getByText('Thinking…')).toBeInTheDocument()
})

test('thinking is said for each agent whose model is thinking, as the canvas says it', () => {
  // The lead waits for two Reviewers and a Coder working at the same time. The Coder's
  // model is writing; the Reviewers' are thinking. The last event was the Coder's word.
  const kid = (id: string, role: string) =>
    agent('r', 'running', { id, parent_agent_id: 'r', role_name: role, name: role, depth: 1 })
  const state = convState({
    runs: [run('old', 'completed'), run('r', 'running')],
    agents: [agent('old', 'completed'), agent('r', 'waiting'), kid('c', 'Coder'), kid('v1', 'Reviewer'), kid('v2', 'Reviewer')],
    messages: [
      userMessage('old', 'before'),
      assistantMessage('m0', 'old', 'Done before.'),
      userMessage('r', 'look'),
      { ...assistantMessage('m1', 'r', 'I ask three.'), agent_id: 'r' },
      { ...assistantMessage('k1', 'r', 'So', 'streaming'), agent_id: 'c' },
    ],
    thinkingRunId: null,
    thinkingAgentId: null,
    thinkingAgents: ['v1', 'v2'],
  })
  const { container, rerender } = render(<MessageList {...handlers} state={state} />)
  const lines = () => Array.from(container.querySelectorAll('.msg-status')).map(line => line.textContent)
  expect(lines()).toEqual(['Reviewer · Thinking…', 'Reviewer · Thinking…'])
  // under the turn they work in, not under an earlier one
  const groups = Array.from(container.querySelectorAll('.msg-group'))
  expect(groups.at(-1)).toHaveTextContent('I ask three.Reviewer · Thinking…')
  expect(groups[1]).not.toHaveTextContent('Thinking…')
  // the lead itself is not named: the chat is its conversation
  rerender(<MessageList {...handlers} state={{ ...state, thinkingAgents: ['r', 'v2'] }} />)
  expect(lines()).toEqual(['Thinking…', 'Reviewer · Thinking…'])
  // one that wrote or finished its step is no longer in the list: nothing is said for it
  rerender(<MessageList {...handlers} state={{ ...state, thinkingAgents: [] }} />)
  expect(lines()).toEqual([])
})

const spawned = convState({
  runs: [run('r', 'waiting_approval')],
  agents: [
    agent('r'),
    agent('r', 'proposed', { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Coder', task: 'Fix the greeting', depth: 1, tools: ['edit_file'] }),
  ],
  messages: [
    userMessage('r', 'fix it'),
    assistantMessage('m', 'r', 'I will hand this over.'),
    { ...assistantMessage('m2', 'r', 'child private thoughts'), agent_id: 'kid' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Coder","task":"Fix the greeting"}', { message_id: 'm' }),
    toolCall('2', 'r', 'read_file', 'succeeded', '{"path":"secret.py"}', { message_id: 'm2', agent_id: 'kid' }),
  ],
})

test('the chat is the lead agent’s conversation: sub-agent messages stay out', () => {
  render(<MessageList {...handlers} state={spawned} />)
  expect(screen.getByText('I will hand this over.')).toBeInTheDocument()
  expect(screen.queryByText('child private thoughts')).not.toBeInTheDocument()
  expect(screen.queryByText('read_file secret.py')).not.toBeInTheDocument()
})

test('a spawn call is one row with its approval card, and both report back', async () => {
  const onSelectAgent = vi.fn()
  const onDecideSpawn = vi.fn().mockResolvedValue(undefined)
  render(<MessageList {...handlers} state={spawned} onSelectAgent={onSelectAgent} onDecideSpawn={onDecideSpawn} />)
  await userEvent.click(screen.getByRole('button', { name: /Coder.*Fix the greeting/ }))
  expect(onSelectAgent).toHaveBeenCalledWith('kid')
  expect(screen.getByText('Open this sub-agent?')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open agent' }))
  expect(onDecideSpawn).toHaveBeenCalledWith('kid', 'approve')
})

// B-99: every kind a recipe asks (`_ask_row`), with the choices it carries - whoever opened the step's agent: the Lead
// (under its call), a team's lead (with what its team asks), or the Lead's room (under the room's row).
test.each([
  ['an Ask me step', 'Web app: Build it is done. Go on with the Feature recipe?', ['Go on', 'Stop'], 'Go on with the recipe?'],
  ['a step that failed', 'Web app: Test it failed (Tester). Try it again, skip it, or stop the Feature recipe?', ['Try again', 'Skip', 'Stop'], 'A recipe step did not finish'],
  ['a role that cannot run', 'Web app: Tester can’t run on Qoder (its limit is reached). Run Test it on Claude Code?', ['Run there', 'Skip', 'Stop'], 'KOLONİ needs your word'],
  // (KOLONİ's Ready for you card is one line in the chat: K-hazir-satir.)
  ['Ready for you', 'Ready for you: Web app (Feature): ready. Take the work into the project?', ['Take in', 'Ask for changes'], "Teams' work is ready"],
])('%s is answered in the chat, by any of its choices, wherever its agent was opened', async (_kind, asked, options, title) => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const last = options[options.length - 1]
  const spec = { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Tester', task: 'Test it', depth: 1 }
  const where = {
    lead: { agents: [agent('r', 'completed', spec)], questions: [question('q', 'r', { tool_call_id: '1', question: asked, options, leave: true })] },
    'team lead': {
      agents: [
        agent('r', 'running', { ...spec, id: 'tl', role_name: 'Web app lead', task: 'Lead Web app' }),
        agent('r', 'completed', { ...spec, parent_agent_id: 'tl', tool_call_id: '7', depth: 2 }),
      ],
      questions: [question('q', 'r', { agent_id: 'tl', tool_call_id: '7', question: asked, options, leave: true })],
    },
  }
  for (const [, over] of Object.entries(where)) {
    const { unmount } = render(
      <MessageList
        {...handlers}
        onAnswer={onAnswer}
        state={convState({
          runs: [run('r', 'waiting_approval')],
          agents: [agent('r', 'waiting'), ...over.agents],
          messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
          toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Tester"}', { message_id: 'm' })],
          questions: over.questions,
        })}
      />,
    )
    // (A title of KOLONİ's own, its words whole under it - sample A.)
    expect(screen.getByText(title)).toBeInTheDocument()
    if (!asked.startsWith('Ready for you')) expect(screen.getByText(asked)).toHaveClass('card-said')
    for (const option of options) expect(screen.getByRole('button', { name: option })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: last }))
    // (B-114: Ask for changes first asks what to change - here sent with nothing written)
    if (last === 'Ask for changes') await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(onAnswer).toHaveBeenLastCalledWith('q', last)
    unmount()
  }
})

test('K-hazir-satir: the teams’ Ready for you card is one line in the chat - what each team changed, its choices, and the way to the card in full', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const row = (team_id: string, team: string, agents: string[], recipe = '') => ({
    team_id,
    recipe_id: null,
    no_recipe: false,
    picked_by: 'user' as const,
    why: null,
    state: { run_id: 'r', team, recipe, status: 'ready' as const, why: null, steps: [], agents, ended_ready: false, passes: [] },
  })
  const asked = question('q', 'r', { tool_call_id: '1', question: 'Ready for you: Web app (Feature): ready; Docs (no recipe): done. Take the work into the project?', options: ['Take in', 'Ask for changes'], leave: true })
  const base = convState()
  const state = convState({
    conversation: { ...base.conversation, teams_mode: 'manual', teams: [row('web', 'Web app', ['c'], 'Feature'), row('docs', 'Docs', ['d'])] },
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'completed', { id: 'c', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Coder', task: 't', depth: 1 })],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Coder"}', { message_id: 'm' })],
    fileChanges: ['a.py', 'b.py', 'a.py', 'c.py'].map((path, at) => fileChange(`f${at}`, 'r', { agent_id: 'c', path })).concat(fileChange('f9', 'r', { agent_id: 'd', path: 'README.md' })),
    questions: [asked],
  })
  const { rerender } = render(<MessageList {...handlers} state={state} onAnswer={onAnswer} />)
  expect(screen.getByText("Teams' work is ready · Web app 3 files · Docs 1 file, kept apart")).toBeInTheDocument()
  expect(screen.queryByText(/Ready for you/)).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
  // details →: Ready for you's panel, at this card (tek-ev §1).
  const { useApp } = await import('../state/store')
  await userEvent.click(screen.getByRole('button', { name: 'details →' }))
  expect(useApp.getState().readyPanel).toEqual({ open: true, at: 'waiting-q' })
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'Take in')
  // Answered - here or on the list, the one question: the line and the answer, still not titled Ready for you.
  rerender(<MessageList {...handlers} state={{ ...state, questions: [{ ...asked, status: 'answered', answer: 'Take in' }] }} onAnswer={onAnswer} />)
  expect(screen.getByText("Teams' work is ready · Web app 3 files · Docs 1 file, kept apart")).toBeInTheDocument()
  expect(screen.getByText('Take in')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Take in' })).not.toBeInTheDocument()
  expect(screen.queryByText(/Ready for you/)).not.toBeInTheDocument()
})

test('the ready line says what changes what Take in does: a row not at its end and why, what one that stopped left that comes in, one kept apart', () => {
  // (The review of K-hazir-satir, M1: the line said less than the card, and Take in could be pressed thinking Docs' file comes in.)
  const row = (team_id: string, team: string, agents: string[], more: object) => ({
    team_id,
    recipe_id: null,
    no_recipe: false,
    picked_by: 'user' as const,
    why: null,
    state: { run_id: 'r', team, recipe: 'Feature', status: 'ready' as const, why: null, steps: [], agents, ended_ready: false, passes: [], ...more },
  })
  const base = convState()
  const asked = question('q', 'r', { tool_call_id: '1', question: 'Ready for you: … Take the work into the project?', options: ['Take in', 'Ask for changes'], leave: true, created_at: '2026-10-05T10:05:00Z' })
  const state = convState({
    conversation: {
      ...base.conversation,
      teams_mode: 'manual',
      teams: [
        row('web', 'Web app', ['c'], { status: 'stopped', why: 'Stopped by you' }),
        row('api', 'Backend', ['b'], {}),
        row('docs', 'Docs', ['d'], { recipe: '', status: 'done' }),
        row('qa', 'Quality', ['t'], { recipe: '', status: 'done' }),
      ],
    },
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'completed', { id: 'c', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Coder', task: 't', depth: 1 })],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Coder"}', { message_id: 'm' })],
    fileChanges: [
      fileChange('f1', 'r', { agent_id: 'c', path: 'a.py', status: 'in_copy' }),
      fileChange('f2', 'r', { agent_id: 'b', path: 'api.py' }),
      fileChange('f3', 'r', { agent_id: 'd', path: 'README.md' }),
    ],
    questions: [asked],
  })
  const { rerender } = render(<MessageList {...handlers} state={state} />)
  // K-r152: a team stopped, so no "Teams' work is ready": each team says its own state.
  const line = 'Web app stopped: Stopped by you (1 file) · Backend is ready (1 file) · Docs is ready (1 file, kept apart) · Quality is ready (nothing to take in)'
  expect(screen.getByText(`${line} · Take in also takes in what Web app left before it stopped.`)).toBeInTheDocument()
  // Answered: counted as it was asked - a file changed later is not in it - and what came of it is the answer's.
  const later = fileChange('f4', 'r', { agent_id: 'b', path: 'more.py', created_at: '2026-10-05T10:09:00Z' })
  rerender(<MessageList {...handlers} state={{ ...state, fileChanges: [...state.fileChanges, later], questions: [{ ...asked, status: 'answered', answer: 'Take in' }] }} />)
  expect(screen.getByText('Web app stopped (1 file) · Backend is ready (1 file) · Docs is ready (1 file, kept apart) · Quality is ready (nothing to take in)')).toBeInTheDocument()
})

test('K-r152: a team whose lead failed at once is not "ready" in the line', () => {
  const row = (team_id: string, team: string, agents: string[]) => ({
    team_id,
    recipe_id: null,
    no_recipe: false,
    picked_by: 'user' as const,
    why: null,
    state: { run_id: 'r', team, recipe: 'Feature', status: 'ready' as const, why: null, steps: [], agents, ended_ready: false, passes: [] },
  })
  const base = convState()
  const asked = question('q', 'r', { tool_call_id: '1', question: 'Ready for you: … Take the work into the project?', options: ['Take in'], leave: true })
  const state = convState({
    conversation: { ...base.conversation, teams_mode: 'manual', teams: [row('docs', 'Docs', ['d']), row('web', 'Web app', ['w'])] },
    runs: [run('r', 'waiting_approval')],
    agents: [
      agent('r', 'waiting'),
      agent('r', 'completed', { id: 'd', parent_agent_id: 'r', role_name: 'Docs lead', depth: 1 }),
      agent('r', 'failed', { id: 'w', parent_agent_id: 'r', role_name: 'Web app lead', depth: 1 }),
    ],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Coder"}', { message_id: 'm' })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'd', path: 'README.md' })],
    questions: [asked],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText('Docs is ready (1 file) · Web app failed (0 files)')).toBeInTheDocument()
})

test('K-r152: an agent’s report is markdown, folded to one line with KOLONİ’s record under it; KOLONİ’s frame of it is not shown', async () => {
  const report = 'Docs lead finished.\n\n### Summary\n\nI wrote **setup.md** for new users. It has three parts.\n\n```\nnpm start\n```\n\nWhat it did, from KOLONİ\'s record: read 2 files, wrote 1 ("setup.md"), ran 0 commands'
  const frame = 'KOLONİ, of your spawn_agent for Docs lead (failed): what came of it follows, as a message from Docs lead.'
  const said = (id: string, content: string, from: string | null): Message => ({ ...assistantMessage(id, 'r', content), role: 'agent', agent_id: 'r', from_agent_id: from })
  const state = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running'), agent('r', 'completed', { id: 'd', parent_agent_id: 'r', role_name: 'Docs lead', depth: 1 })],
    messages: [userMessage('r', 'x'), said('k', frame, null), said('n', report, 'd'), said('s', 'Which **file**?', 'd'), assistantMessage('m', 'r', 'All done.')],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.queryByText(/what came of it follows/)).toBeNull()
  const head = screen.getByRole('button', { name: /Docs lead · done · I wrote setup\.md for new users\.$/ })
  expect(head).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByText('npm start')).toBeNull()
  expect(screen.getByText(/^What it did, from KOLONİ's record: read 2 files/)).toBeInTheDocument()
  await userEvent.click(head)
  expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument()
  expect(screen.getByText('npm start')).toBeInTheDocument()
  expect(screen.getAllByText(/^What it did, from KOLONİ's record/)).toHaveLength(1)
  // A short message is not folded: its markdown is drawn.
  expect(screen.getByText('file').tagName).toBe('STRONG')
})

test('K-r152: a failed report’s line says its name once, then why', () => {
  const failed = 'Web app lead failed: the model said no tokens\n\nWhat it did, from KOLONİ\'s record: read 0 files, wrote 0, ran 0 commands'
  const state = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running'), agent('r', 'failed', { id: 'w', parent_agent_id: 'r', role_name: 'Web app lead', depth: 1 })],
    messages: [userMessage('r', 'x'), { ...assistantMessage('n', 'r', failed), role: 'agent', agent_id: 'r', from_agent_id: 'w' }],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('button', { name: /^\s*Web app lead · failed · the model said no tokens$/ })).toBeInTheDocument()
})

test('B-362: an answer KOLONİ hands on as data is folded, with its real line breaks', async () => {
  const late = 'KOLONİ: Spec writer\'s answer to Docs lead was not delivered - Docs lead ended (failed) before it came. The answer, as data: "## Spec\\n\\nOne page.\\nTwo parts."'
  const toLead = 'KOLONİ: Coder of the Web app team asked the Docs team for work, and it did not reach them: it is not open. The request, as data: "a README". Decide what becomes of it: open Docs\'s coordinator with it, or tell Coder.'
  const said = (id: string, content: string): Message => ({ ...assistantMessage(id, 'r', content), role: 'agent', agent_id: 'r', from_agent_id: 'c' })
  const state = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running'), agent('r', 'running', { id: 'c', parent_agent_id: 'r', role_name: 'Coder', depth: 1 })],
    messages: [userMessage('r', 'x'), said('k', late), said('t', toLead)],
  })
  render(<MessageList {...handlers} state={state} />)
  // KOLONİ's words, though sent in the asker's name.
  expect(screen.getAllByText('from KOLONİ')).toHaveLength(2)
  expect(screen.getByText(/before it came\.$/)).toBeInTheDocument()
  expect(screen.getByText(/it is not open\. Decide what becomes of it/)).toBeInTheDocument()
  expect(screen.queryByText(/as data/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'The answer' }))
  expect(screen.getByText(/One page\./).textContent).toBe('## Spec\n\nOne page.\nTwo parts.')
})

test('a question a recipe’s Room step puts in the Lead’s room call is answered under the room’s row (B-99)', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const asked = 'Web app: Design meeting failed (Coder). Skip it, or stop the Odali recipe?'
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'failed', { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Coder', task: 't', depth: 1 })],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'open_room', 'running', '{"goal":"Design"}', { message_id: 'm' })],
    questions: [question('q', 'r', { tool_call_id: '1', question: asked, options: ['Skip', 'Stop'], leave: true })],
  })
  render(<MessageList {...handlers} state={state} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'Skip')
})

test('a recipe’s question, put in the call that opened its step’s agent, is answered under that agent’s row (B-99)', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'completed', { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Spec writer', task: 'Write the spec', depth: 1 })],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Spec writer","task":"Write the spec"}', { message_id: 'm' })],
    questions: [question('q', 'r', { tool_call_id: '1', question: 'Web app: Write the spec is done. Go on with the Feature recipe?', options: ['Go on', 'Stop'], leave: true })],
  })
  const { rerender } = render(<MessageList {...handlers} state={state} onAnswer={onAnswer} />)
  expect(screen.getByRole('button', { name: /Spec writer.*Write the spec/ })).toBeInTheDocument()
  expect(screen.getByText('Go on with the recipe?')).toHaveClass('cmd-approval-kicker')
  expect(screen.getByText('Web app: Write the spec is done. Go on with the Feature recipe?')).toHaveClass('card-said')
  await userEvent.click(screen.getByRole('button', { name: 'Go on' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'Go on')
  // answered: what was asked and said stays, and no card
  const answered = { ...state.questions[0], status: 'answered' as const, answer: 'Go on' }
  rerender(<MessageList {...handlers} state={{ ...state, questions: [answered] }} onAnswer={onAnswer} />)
  expect(screen.getByText('Web app: Write the spec is done. Go on with the Feature recipe?')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  // the recipe's next question, in the same call: under the first, and answered there
  const takeIn = question('q2', 'r', { tool_call_id: '1', question: 'Ready for you: Web app (Feature): ready. Take the work into the project?', options: ['Take in', 'Ask for changes'], leave: true })
  rerender(<MessageList {...handlers} state={{ ...state, questions: [answered, takeIn] }} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onAnswer).toHaveBeenCalledWith('q2', 'Take in')
})

test('a spawn that never opened an agent stays an ordinary tool row', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'failed', '{"role":"Nobody","task":"x"}', { message_id: 'm' })],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('button', { name: /spawn_agent Nobody/ })).toBeInTheDocument()
  expect(screen.queryByText('Open this sub-agent?')).not.toBeInTheDocument()
})

test('the Lead’s pick of teams stands in the chat as its own line, not folded into a run (slice 84b)', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [
      toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}', { message_id: 'm' }),
      toolCall('2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}', { message_id: 'm' }),
      toolCall('3', 'r', 'pick_teams', 'succeeded', '{"teams":[{"team":"Docs","why":"it is words"}]}', { message_id: 'm' }),
    ],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('button', { name: /pick_teams Docs: it is words/ })).toBeVisible()
})

test('a role an agent wants to create is asked for under its call', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r')],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'create_role', 'running', '{"name":"Documenter","tools":["read_file"]}', { message_id: 'm' })],
    pendingRoles: [{ tool_call_id: '1', run_id: 'r', agent_id: 'r', name: 'Documenter', description: '', instructions: '', tools: ['read_file'] }],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByRole('button', { name: /create_role Documenter/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Create role' }))
  expect(onDecideRole).toHaveBeenCalledWith('1', 'approve')
})

// A lead that opened a Planner, which opened a Coder; each of them asks for something.
const asking = convState({
  runs: [run('r', 'waiting_approval')],
  agents: [
    agent('r', 'waiting'),
    agent('r', 'waiting', { id: 'planner', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Planner', task: 'plan it', depth: 1 }),
    agent('r', 'running', { id: 'coder', parent_agent_id: 'planner', tool_call_id: '2', role_name: 'Coder', task: 'code it', depth: 2 }),
    agent('r', 'proposed', { id: 'tester', parent_agent_id: 'planner', tool_call_id: '3', role_name: 'Tester', task: 'test it', depth: 2 }),
  ],
  messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
  toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Planner"}', { message_id: 'm' })],
  pendingRoles: [{ tool_call_id: '9', run_id: 'r', agent_id: 'planner', name: 'Documenter', description: '', instructions: '', tools: ['read_file'] }],
  commands: [command('k1', 'r', { agent_id: 'coder', status: 'proposed', command: 'pytest -q', exit_code: null, started_at: null, ended_at: null })],
  fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', status: 'proposed', path: 'src/deep.py' })],
})

test('what sub-agents ask for is answered in the chat, each request naming who asks', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const onDecideCommand = vi.fn().mockResolvedValue(undefined)
  const onDecideSpawn = vi.fn().mockResolvedValue(undefined)
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(
    <MessageList
      {...handlers}
      state={asking}
      onDecide={onDecide}
      onDecideRole={onDecideRole}
      onDecideCommand={onDecideCommand}
      onDecideSpawn={onDecideSpawn}
    />,
  )
  expect(screen.getAllByText('Planner asks')).toHaveLength(2) // its role, and the Tester it wants
  expect(screen.getAllByText('Coder asks')).toHaveLength(2) // its command and its file change
  await userEvent.click(screen.getByRole('button', { name: 'Create role' }))
  expect(onDecideRole).toHaveBeenCalledWith('9', 'approve')
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  expect(onDecideCommand).toHaveBeenCalledWith('k1', 'once')
  await userEvent.click(screen.getByRole('button', { name: 'Open agent' }))
  expect(onDecideSpawn).toHaveBeenCalledWith('tester', 'approve')
  expect(screen.getByText('src/deep.py')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(onDecide).toHaveBeenCalledWith('f1', 'approve')
})

test('a sub-agent’s command card says why it is asked, as its call’s record says', () => {
  const why = 'it names the project folder (C:\\p), outside the working copy it works in: there it would act on the project itself'
  const state = {
    ...asking,
    toolCalls: [...asking.toolCalls, toolCall('c', 'r', 'run_command', 'running', '{"command":"pytest -q"}', { agent_id: 'coder', message_id: 'coder-step', why_asked: why })],
    commands: [{ ...asking.commands[0], tool_call_id: 'c' }],
  }
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText(why)).toHaveAttribute('role', 'note')
})

test('requests that were answered leave the chat', () => {
  const settled = {
    ...asking,
    pendingRoles: [],
    commands: [command('k1', 'r', { agent_id: 'coder' })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', status: 'applied' })],
    agents: asking.agents.map(a => (a.id === 'tester' ? { ...a, status: 'running' as const } : a)),
  }
  render(<MessageList {...handlers} state={settled} />)
  expect(screen.queryByText(/ asks$/)).not.toBeInTheDocument()
})

const askedBy = (over: Parameters<typeof question>[2] = {}) =>
  convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r')],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'ask_user', 'running', '{"question":"Which greeting?"}', { message_id: 'm' })],
    questions: [question('q', 'r', { options: ['hello', 'hey'], ...over })],
  })

test('a question the lead asks is answered under its call', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  render(<MessageList {...handlers} state={askedBy()} onAnswer={onAnswer} />)
  expect(screen.getByText('Which greeting?')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'hey' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'hey')
})

test('a message queued behind a question says it waits for the answer, under the card', () => {
  // K-lead-bekliyor (R116)
  const WAITS_FOR_ANSWER = 'Your message waits until this question is answered'
  const { rerender } = render(<MessageList {...handlers} state={askedBy()} />)
  expect(screen.queryByText(WAITS_FOR_ANSWER)).not.toBeInTheDocument()
  const asked = askedBy()
  const queued = convState({
    ...asked,
    runs: [...asked.runs, run('q2', 'queued', { started_at: null })],
    messages: [...asked.messages, userMessage('q2', 'and then')],
  })
  rerender(<MessageList {...handlers} state={queued} />)
  const text = document.body.textContent ?? ''
  expect(text.indexOf('Which greeting?')).toBeLessThan(text.indexOf(WAITS_FOR_ANSWER))
  expect(text.indexOf(WAITS_FOR_ANSWER)).toBeLessThan(text.indexOf('and then'))
})

test('an answered question shows the question and what you said, and no card', () => {
  render(<MessageList {...handlers} state={askedBy({ status: 'answered', answer: 'hey' })} />)
  expect(screen.getByText('Which greeting?')).toBeInTheDocument()
  expect(screen.getByText('hey')).toBeInTheDocument()
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
  expect(screen.queryByText(/ask_user/)).not.toBeInTheDocument()
})

test('a question nobody answered says so', () => {
  render(<MessageList {...handlers} state={askedBy({ status: 'cancelled' })} />)
  expect(screen.getByText('not answered')).toBeInTheDocument()
})

const leaveAsked = (status: 'running' | 'succeeded', over: Parameters<typeof question>[2] = {}) =>
  convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r')],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'rea__scan', status, '{"target":"a.exe"}', { message_id: 'm' })],
    questions: [question('q', 'r', { question: 'May the tool "scan" of the MCP server "rea" run?', options: ['Allow', 'Deny'], leave: true, ...over })],
  })

test('a call of an MCP server’s tool keeps its row while leave is asked for it, and waits', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  render(<MessageList {...handlers} state={leaveAsked('running')} onAnswer={onAnswer} />)
  // by the server and the tool, and not as running: nothing of it runs before the yes
  const row = screen.getByRole('button', { name: /rea · scan: waits for your answer/ })
  expect(within(row).getByText('waiting')).toBeInTheDocument()
  expect(screen.queryByText('running')).not.toBeInTheDocument()
  expect(screen.getByText('May the tool "scan" of the MCP server "rea" run?')).toBeInTheDocument()
  // the question is KOLONİ's, under a title of its own, and Allow and Reject are all there is to say to it
  expect(screen.getByText('KOLONİ asks')).toBeInTheDocument()
  expect(screen.getByText('Allow this?')).toHaveClass('cmd-approval-kicker')
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Allow' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'Allow')
})

test('leave asked for a sub-agent’s call says whose call it is, and that the agent asks nothing', () => {
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [
      agent('r', 'waiting'),
      agent('r', 'running', { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Reviewer', task: 't', depth: 1 }),
    ],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Reviewer","task":"t"}', { message_id: 'm' })],
    questions: [question('q', 'r', { agent_id: 'kid', tool_call_id: '7', question: 'May the tool "scan" of the MCP server "rea" run?', options: ['Allow', 'Deny'], leave: true })],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText('for Reviewer')).toBeInTheDocument()
  expect(screen.queryByText('Reviewer asks')).not.toBeInTheDocument()
  expect(screen.getByText('KOLONİ asks')).toBeInTheDocument()
})

test('once leave was given the call’s row is still there, with what was asked and said', () => {
  render(<MessageList {...handlers} state={leaveAsked('succeeded', { status: 'answered', answer: 'Allow' })} />)
  expect(screen.getByRole('button', { name: /^rea · scan\s*done$/ })).toBeInTheDocument()
  expect(screen.getByText('May the tool "scan" of the MCP server "rea" run?')).toBeInTheDocument()
  expect(screen.getByText('Allow')).toBeInTheDocument()
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
})

test('a sub-agent’s question is answered in the chat and names who asks', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [
      agent('r', 'waiting'),
      agent('r', 'running', { id: 'kid', parent_agent_id: 'r', tool_call_id: '1', role_name: 'Reviewer', task: 't', depth: 1 }),
    ],
    messages: [userMessage('r', 'x'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'spawn_agent', 'running', '{"role":"Reviewer"}', { message_id: 'm' })],
    questions: [question('q', 'r', { agent_id: 'kid', tool_call_id: '7', question: 'Strict or lenient?' })],
  })
  render(<MessageList {...handlers} state={state} onAnswer={onAnswer} />)
  expect(screen.getByText('Reviewer asks')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Your answer'), 'strict')
  await userEvent.click(screen.getByRole('button', { name: 'Send answer' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'strict')
})

test('a question from two levels down is still answered in the chat', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const state = { ...asking, pendingRoles: [], commands: [], fileChanges: [], questions: [question('deep', 'r', { agent_id: 'coder', tool_call_id: '8', question: 'Tabs or spaces?', options: ['tabs', 'spaces'] })] }
  render(<MessageList {...handlers} state={state} onAnswer={onAnswer} />)
  expect(screen.getByText('Coder asks')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'spaces' }))
  expect(onAnswer).toHaveBeenCalledWith('deep', 'spaces')
  expect(screen.getAllByText('Tabs or spaces?')).toHaveLength(1)
})

// --- a turn nobody was watching (slice 18a) --------------------------------------------------

const refusedWith = (what: string) =>
  `not done: nobody is here to ask. This turn was started by the trigger "Nightly look", which does not allow it to ${what}. ` +
  "That is the user's standing decision, not a tool error: do not try it another way. Go on with what you may do, and say in your report what you would have asked for."

function unattended(over: Parameters<typeof convState>[0] = {}) {
  const started: Message = { ...userMessage('n', 'Look the project over.'), id: 't-n', role: 'trigger' }
  return convState({
    runs: [run('n', 'completed', { unattended: true, trigger_id: 't1', trigger_name: 'Nightly look' })],
    agents: [agent('n', 'completed')],
    messages: [started, assistantMessage('m1', 'n', ''), assistantMessage('m2', 'n', 'I could not do everything.')],
    toolCalls: [
      toolCall('1', 'n', 'write_file', 'denied', '{"path":"made.txt","content":"x"}', { message_id: 'm1', result: refusedWith('change files') }),
      toolCall('2', 'n', 'run_command', 'denied', '{"command":"python check.py"}', { message_id: 'm1', result: refusedWith('run "python check.py"') }),
      toolCall('3', 'n', 'ask_user', 'denied', '{"question":"Which?"}', { message_id: 'm1', result: refusedWith('ask the user anything') }),
    ],
    ...over,
  })
}

test('a turn a trigger started begins with a badge that names the trigger and says nobody was watching', () => {
  render(<MessageList state={unattended()} {...handlers} />)
  const badge = screen.getByRole('note', { name: 'Started by the trigger Nightly look' })
  expect(badge).toHaveTextContent('started by the trigger Nightly look')
  expect(badge).toHaveTextContent('nobody watching')
  expect(screen.getByText('Look the project over.')).toBeInTheDocument()
})

test('at the end of such a turn, what it would have asked you is listed once, each request with a way to allow it where a trigger can', async () => {
  const onAllow = vi.fn()
  render(<MessageList state={unattended()} {...handlers} onAllowInTrigger={onAllow} />)
  const block = screen.getByRole('group', { name: 'It would have asked you' })
  const asked = within(block).getAllByRole('listitem')
  expect(asked.map(item => item.firstChild?.textContent)).toEqual(['write made.txt', 'run `python check.py`', 'ask the user anything'])
  // it stands after the turn's last words, not among them
  expect(screen.getByText('I could not do everything.').compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  // what no trigger can allow has no link
  expect(within(asked[2]).queryByRole('button')).not.toBeInTheDocument()
  await userEvent.click(within(asked[0]).getByRole('button', { name: 'Allow this in the trigger' }))
  expect(onAllow).toHaveBeenLastCalledWith('t1', { write: true })
  await userEvent.click(within(asked[1]).getByRole('button', { name: 'Allow this in the trigger' }))
  expect(onAllow).toHaveBeenLastCalledWith('t1', { command: 'python check.py' })
})

test('a turn that was refused nothing has no such block; nor has a turn of the user’s, whatever its tools said', () => {
  const { unmount } = render(<MessageList state={unattended({ toolCalls: [] })} {...handlers} />)
  expect(screen.queryByRole('group', { name: 'It would have asked you' })).not.toBeInTheDocument()
  unmount()
  const own = convState({
    runs: [run('r', 'completed')],
    messages: [userMessage('r', 'x'), assistantMessage('m1', 'r', 'done')],
    toolCalls: [toolCall('1', 'r', 'write_file', 'denied', '{"path":"a"}', { message_id: 'm1', result: refusedWith('change files') })],
  })
  render(<MessageList state={own} {...handlers} />)
  expect(screen.queryByRole('group', { name: 'It would have asked you' })).not.toBeInTheDocument()
})

test('a trigger that is no longer on record cannot be allowed anything: the requests are listed without the link', () => {
  const state = unattended({ runs: [run('n', 'completed', { unattended: true, trigger_id: null, trigger_name: 'Nightly look' })] })
  render(<MessageList state={state} {...handlers} onAllowInTrigger={vi.fn()} />)
  const block = screen.getByRole('group', { name: 'It would have asked you' })
  expect(within(block).getAllByRole('listitem')).toHaveLength(3)
  expect(within(block).queryByRole('button')).not.toBeInTheDocument()
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test('where the topic changes there is a divider: a new topic the first time, and the topic by name when the talk comes back to it', () => {
  const started: Message = { ...userMessage('n', 'Look the project over.'), id: 't-n', role: 'trigger' }
  const state = convState({
    topics: [topic('ta', 'Fix the greeting'), topic('tb', 'Write the docs'), topic('tn', 'Look the project over.', { trigger_id: 't1' })],
    runs: [
      run('a1', 'completed', { topic_id: 'ta' }),
      run('a2', 'completed', { topic_id: 'ta' }),
      run('b1', 'completed', { topic_id: 'tb' }),
      run('n', 'completed', { unattended: true, trigger_id: 't1', trigger_name: 'Nightly look', topic_id: 'tn' }),
      run('a3', 'completed', { topic_id: 'ta' }),
    ],
    messages: [
      userMessage('a1', 'Fix the greeting'),
      assistantMessage('m1', 'a1', 'Done.'),
      userMessage('a2', 'now in Turkish'),
      userMessage('b1', 'Write the docs'),
      started,
      userMessage('a3', 'and in German'),
    ],
  })
  render(<MessageList state={state} {...handlers} />)
  // nothing before the first turn, nothing between two turns of one topic
  expect(screen.getAllByRole('separator').map(divider => divider.textContent)).toEqual([
    'New topic: Write the docs',
    'New topic: Nightly look',
    'Continuing: Fix the greeting',
  ])
  // in reading order: each stands before the turn it opens
  const order = Array.from(document.querySelectorAll('.topic-divider, .msg-bubble, .msg-quote')).map(piece => piece.textContent)
  expect(order).toEqual([
    'Fix the greeting',
    'now in Turkish',
    'New topic: Write the docs',
    'Write the docs',
    'New topic: Nightly look',
    'Look the project over.',
    'Continuing: Fix the greeting',
    'and in German',
  ])
  // a trigger's turn keeps its badge
  expect(screen.getByRole('note', { name: 'Started by the trigger Nightly look' })).toBeInTheDocument()
})

test('turns on record with no topic have no divider between them', () => {
  const state = convState({
    runs: [run('a', 'completed'), run('b', 'completed')],
    messages: [userMessage('a', 'one'), userMessage('b', 'two')],
  })
  render(<MessageList state={state} {...handlers} />)
  expect(screen.queryByRole('separator')).not.toBeInTheDocument()
})

test('the card that asks before an agent goes on from an earlier turn says so', () => {
  const state = convState({
    topics: [topic('ta', 'Fix the greeting')],
    runs: [run('a1', 'completed', { topic_id: 'ta' }), run('a2', 'waiting_approval', { topic_id: 'ta' })],
    messages: [userMessage('a1', 'Fix the greeting'), userMessage('a2', 'go on'), assistantMessage('m2', 'a2', '')],
    agents: [
      agent('a1', 'completed'),
      agent('a1', 'completed', { id: 'coder1', parent_agent_id: 'a1', role_name: 'Coder', depth: 1 }),
      agent('a2', 'waiting'),
      agent('a2', 'proposed', { id: 'coder2', parent_agent_id: 'a2', role_name: 'Coder', depth: 1, continues_id: 'coder1', tool_call_id: '7', task: 'Now in Turkish' }),
    ],
    toolCalls: [toolCall('7', 'a2', 'message_agent', 'running', '{"to":"Coder","message":"Now in Turkish"}', { message_id: 'm2' })],
  })
  const { rerender } = render(<MessageList state={state} {...handlers} />)
  expect(screen.getByText(`continues Coder from the ${when('2026-10-05T10:00:00Z')} message`)).toBeInTheDocument()
  // with the roles not known here, only where it stays is said
  expect(screen.getByText('It stays on Local · qwen, where it ran before.')).toBeInTheDocument()
  // its role runs elsewhere now: the card says where, and that this agent stays where it ran before
  const providers = [{ id: 'p-local', name: 'Local', default_model: 'qwen' }, { id: 'p-fast', name: 'Fast', default_model: 'quick' }] as Provider[]
  const coder = (over: Partial<Role>) => [{ id: 'r', name: 'Coder', provider_id: null, model_id: null, ...over }] as Role[]
  rerender(<MessageList state={state} {...handlers} roles={coder({ provider_id: 'p-fast' })} providers={providers} />)
  expect(screen.getByText('It stays on Local · qwen, where it ran before. Its role would now run on Fast · quick.')).toBeInTheDocument()
  // its role would run where it runs: nothing is said
  rerender(<MessageList state={state} {...handlers} roles={coder({})} providers={providers} />)
  expect(screen.queryByText(/It stays on/)).not.toBeInTheDocument()
})

test('a plan turn ends with its plan card; the decision goes with the turn it is of', async () => {
  const onDecidePlan = vi.fn().mockResolvedValue(undefined)
  const plan = { text: 'PLAN: 1. look', status: 'proposed' as const, model_id: 'big-model', strongest: true }
  render(
    <MessageList
      {...handlers}
      onDecidePlan={onDecidePlan}
      state={convState({
        runs: [run('o', 'completed', { plan_turn: true, plan }), run('w', 'completed'), run('p', 'completed', { plan_turn: true, plan })],
        messages: [
          userMessage('o', 'make b.txt'),
          assistantMessage('m0', 'o', 'PLAN: 1. look'),
          userMessage('w', 'go'),
          assistantMessage('m2', 'w', 'done'),
          userMessage('p', 'make a.txt'),
          assistantMessage('m1', 'p', 'PLAN: 1. look'),
        ],
      })}
    />,
  )
  // a card under each plan turn, none under the other; the older one only turned down
  expect(screen.getAllByText('Approve this plan?')).toHaveLength(1)
  expect(screen.getAllByText('This plan was not decided')).toHaveLength(1)
  expect(screen.getAllByText(/A later message has started since this plan/)).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(onDecidePlan).toHaveBeenCalledWith('p', 'approve', undefined)
})

const UNDO = { turns: [], revert: ['a.txt'], skip: [], reject: [], copies: [], commands: [], stays: [], note: null }
const AT = '2026-10-26T10:42:00'

test('slice 107: a message whose work changed files has ↺ beside it, named with its time; one that runs, or changed nothing, has none', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(UNDO), { status: 200 })))
  const messages = [{ ...userMessage('a', 'make a'), created_at: AT }, userMessage('b', 'make b'), userMessage('c', 'thanks')]
  const fileChanges = [fileChange('fa', 'a', { path: 'a.txt' }), fileChange('fb', 'b', { path: 'b.txt' })]
  const runs = [run('a', 'completed'), run('b', 'running'), run('c', 'completed')]
  const { rerender } = render(<MessageList {...handlers} state={convState({ runs, messages, fileChanges })} />)
  expect(screen.getAllByRole('button', { name: /^Undo these changes/ })).toHaveLength(1)
  const undo = screen.getByRole('button', { name: `Undo these changes · ${when(AT)}` })
  expect(undo).toHaveAttribute('title', 'Undo these changes')
  await userEvent.click(undo)
  const card = screen.getByRole('region', { name: 'Undo these changes' })
  expect(await within(card).findByRole('region', { name: 'Will be reverted' })).toHaveTextContent('a.txt')
  expect(within(card).getByRole('button', { name: 'Cancel' })).toHaveFocus()
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toBe('/api/runs/a/undo')
  // Undone: its change is reverted, and the card stays to say so; closed, no ↺ is left.
  await userEvent.click(within(card).getByRole('button', { name: 'Undo' }))
  rerender(<MessageList {...handlers} state={convState({ runs, messages, fileChanges: [{ ...fileChanges[0], status: 'reverted' }, fileChanges[1]] })} />)
  expect(await within(card).findByRole('region', { name: 'Reverted' })).toHaveTextContent('a.txt')
  await userEvent.click(within(card).getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('button', { name: /^Undo these changes/ })).toBeNull()
  vi.unstubAllGlobals()
})

test('slice 107: a message’s ⋯ copies it (and says so), restores to before it, and shows its work on the canvas - as does a click on it', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(UNDO), { status: 200 })))
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  const onShowTurn = vi.fn()
  const messages = [{ ...userMessage('a', 'make a'), created_at: AT }, userMessage('b', 'thanks')]
  render(<MessageList {...handlers} onShowTurn={onShowTurn} state={convState({ runs: [run('a', 'completed'), run('b', 'completed')], messages })} />)
  const more = screen.getAllByRole('button', { name: /^Copy, restore, show its work · / })
  expect(more).toHaveLength(2)
  // (its time tells one message's ⋯ from another's)
  expect(more[0]).toHaveAccessibleName(`Copy, restore, show its work · ${when(AT)}`)
  await userEvent.click(more[0])
  const menu = screen.getByRole('menu', { name: 'Copy, restore, show its work' })
  expect(within(menu).getAllByRole('menuitem').map(item => item.textContent?.trim())).toEqual(['Copy', 'Restore to before this message', 'Show its work on the canvas'])
  await userEvent.click(within(menu).getByRole('menuitem', { name: 'Copy' }))
  expect(writeText).toHaveBeenCalledWith('make a')
  expect(await within(menu).findByRole('menuitem', { name: 'Copied' })).toBeInTheDocument()
  await userEvent.click(within(menu).getByRole('menuitem', { name: 'Show its work on the canvas' }))
  expect(onShowTurn).toHaveBeenLastCalledWith('a')
  expect(screen.queryByRole('menu')).toBeNull()
  await userEvent.click(screen.getByText('thanks'))
  expect(onShowTurn).toHaveBeenLastCalledWith('b')
  await userEvent.click(more[0])
  // (opened again it is "Copy" again)
  expect(screen.getByRole('menuitem', { name: 'Copy' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('menuitem', { name: 'Restore to before this message' }))
  const card = screen.getByRole('region', { name: `Restore to before your ${when(AT)} message` })
  expect(await within(card).findByRole('region', { name: 'Will be reverted' })).toHaveTextContent('a.txt')
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toBe('/api/conversations/c/restore?before=a')
  vi.unstubAllGlobals()
})

test('slice 107: a message still queued or at work cannot be restored to before; one of files alone copies their names', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  const files: Attachment = { id: 'f1', conversation_id: 'c', message_id: 'm-a', frame_of: null, name: 'notes.pdf', kind: 'pdf', mime: 'application/pdf', size: 10, summary: '', given_to: [], shown_to: {}, keep_in_project: false, created_at: AT }
  const messages = [{ ...userMessage('a', ''), id: 'm-a' }, userMessage('b', 'go')]
  render(<MessageList {...handlers} onShowTurn={() => {}} state={convState({ runs: [run('a', 'completed'), run('b', 'running')], messages, attachments: [files] })} />)
  const [done, working] = screen.getAllByRole('button', { name: /^Copy, restore, show its work · / })
  await userEvent.click(working)
  expect(screen.queryByRole('menuitem', { name: 'Restore to before this message' })).toBeNull()
  await userEvent.click(working)
  await userEvent.click(done)
  await userEvent.click(screen.getByRole('menuitem', { name: 'Copy' }))
  expect(writeText).toHaveBeenCalledWith('notes.pdf')
})

test('slice 23: a file saved into the project says where under its message, once the change is in', () => {
  const messages = [{ ...userMessage('a', 'keep this'), id: 'm-a' }]
  const saved = [
    fileChange('s1', 'a', { path: 'docs/attachments/2026-11-03-shot.png', attachment_id: 'f1', kind: 'create' }),
    fileChange('s2', 'a', { path: 'docs/attachments/2026-11-03-cart.ts', attachment_id: 'f2', status: 'proposed' }),
    fileChange('s3', 'a', { path: 'src/a.py' }),
  ]
  render(<MessageList {...handlers} state={convState({ runs: [run('a', 'running')], messages, fileChanges: saved })} />)
  expect(screen.getByText('docs/attachments/2026-11-03-shot.png').parentElement).toHaveTextContent('saved to docs/attachments/2026-11-03-shot.png')
  expect(screen.queryByText(/saved to docs\/attachments\/2026-11-03-cart\.ts/)).toBeNull()
  expect(screen.queryByText(/saved to src/)).toBeNull()
})

test('slice 107: a click on a link or a button in a message does not draw its work', async () => {
  const onShowTurn = vi.fn()
  render(<MessageList {...handlers} onShowTurn={onShowTurn} state={convState({ runs: [run('a', 'completed')], messages: [userMessage('a', 'see this')] })} />)
  // (a diagram's "Show source", a link: what the message holds of its own)
  const bubble = screen.getByText('see this').closest('.msg-bubble') as HTMLElement
  const [button, link] = [document.createElement('button'), document.createElement('a')]
  link.append(document.createElement('b'))
  bubble.append(button, link)
  await userEvent.click(button)
  await userEvent.click(link.firstChild as HTMLElement)
  expect(onShowTurn).not.toHaveBeenCalled()
  await userEvent.click(screen.getByText('see this'))
  expect(onShowTurn).toHaveBeenCalledWith('a')
})

test('slice 107: a trigger’s message has the same ⋯ - its work on the canvas, Restore to before it', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(UNDO), { status: 200 })))
  const onShowTurn = vi.fn()
  const byTrigger: Message = { ...userMessage('n', 'Look the project over'), id: 't-n', role: 'trigger', created_at: AT }
  render(<MessageList {...handlers} onShowTurn={onShowTurn} state={convState({ runs: [run('n', 'completed', { unattended: true, trigger_name: 'Nightly look' })], messages: [byTrigger] })} />)
  await userEvent.click(screen.getByRole('button', { name: `Copy, restore, show its work · ${when(AT)}` }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Show its work on the canvas' }))
  expect(onShowTurn).toHaveBeenCalledWith('n')
  await userEvent.click(screen.getByRole('button', { name: /^Copy, restore, show its work/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Restore to before this message' }))
  const card = screen.getByRole('region', { name: `Restore to before the ${when(AT)} message` })
  expect(await within(card).findByRole('region', { name: 'Will be reverted' })).toHaveTextContent('a.txt')
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toBe('/api/conversations/c/restore?before=n')
  vi.unstubAllGlobals()
})

test('scrolled up, a button jumps back to the latest and then goes away', async () => {
  const messages = [userMessage('a', 'make a'), userMessage('b', 'make b')]
  const { container } = render(<MessageList {...handlers} state={convState({ runs: [run('a', 'completed'), run('b', 'completed')], messages })} />)
  const list = container.querySelector('.msg-list') as HTMLDivElement
  Object.defineProperties(list, { scrollHeight: { value: 1000 }, clientHeight: { value: 300 } })
  expect(screen.queryByRole('button', { name: 'Jump to the latest' })).not.toBeInTheDocument()
  list.scrollTop = 100
  fireEvent.scroll(list)
  const jump = screen.getByRole('button', { name: 'Jump to the latest' })
  list.scrollTo = vi.fn()
  await userEvent.click(jump)
  expect(list.scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 1000 }))
  expect(screen.queryByRole('button', { name: 'Jump to the latest' })).not.toBeInTheDocument()
})

test('the user’s fenced code is shown as an answer’s, coloured in its box; the rest of their words stay as written', () => {
  const said = '# not a heading, *not* bold\n```python\ndef greet():\n    return 1\n```\nand after'
  const { container } = render(<MessageList {...handlers} state={convState({ runs: [run('r', 'completed')], messages: [userMessage('r', said)] })} />)
  const bubble = container.querySelector('.msg-user .msg-bubble')!
  expect(bubble.querySelector('h1, em')).toBeNull()
  expect(bubble.firstChild).toHaveProperty('nodeValue', '# not a heading, *not* bold')
  expect(bubble.lastChild).toHaveProperty('nodeValue', 'and after')
  const code = bubble.querySelector('pre code.language-python')!
  expect(code.textContent).toBe('def greet():\n    return 1\n')
  expect(code.querySelector('.hljs-keyword')).toHaveTextContent('def')
})

test('three backticks with more after them on the line are inline code, not a fence: the words stay as written', () => {
  const said = '```inline``` is how\nI wrote it\n```'
  const { container } = render(<MessageList {...handlers} state={convState({ runs: [run('r', 'completed')], messages: [userMessage('r', said)] })} />)
  const bubble = container.querySelector('.msg-user .msg-bubble')!
  expect(bubble.querySelector('pre')).toBeNull()
  expect(bubble.textContent).toBe(said)
})

// --- a Lead's calls in a row are one line (K-ozet-satiri) --------------------------------------

/**
 * A Lead's turn, one call a step, and its words at the end. Each test names its calls apart
 * (`key`): which lines are open and which calls stood alone are kept for the page's session.
 * (`ml-` too: another test file in the same worker - modules shared, isolate: false - may leave a "c3" there.)
 */
function looksAround(key: string, calls: Parameters<typeof toolCall>[], over: Parameters<typeof convState>[0] = {}) {
  return convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'look around'), ...calls.map((_, n) => assistantMessage(`m${n}`, 'r', '')), assistantMessage('end', 'r', 'Found it.')],
    toolCalls: calls.map(([id, runId, name, status, args, more], n) => toolCall(`ml-${key}${id}`, runId, name, status, args, { message_id: `m${n}`, ...more })),
    ...over,
  })
}

const OUTSIDE = { started_at: '2026-10-05T10:00:02Z', outside_folder: 'D:\\x' }

test('calls in a row are one closed line that counts them; opened, the rows are there as ever and each opens', async () => {
  const state = looksAround('a', [
    ['1', 'r', 'list_dir', 'succeeded', '{}'],
    ['2', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
    ['3', 'r', 'read_file', 'failed', '{"path":"gone.py"}'],
  ])
  render(<MessageList {...handlers} state={state} />)
  const head = screen.getByRole('button', { name: 'Read 1 file, listed 1 folder, 1 failed, 3 calls, done' })
  expect(head).toHaveAttribute('aria-expanded', 'false')
  expect(head).toHaveTextContent('1 failed')
  expect(screen.queryByText('read_file a.py')).not.toBeInTheDocument()
  // (its words stay outside it, after it)
  expect(head.compareDocumentPosition(screen.getByText('Found it.')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

  head.focus()
  await userEvent.keyboard('{Enter}')
  expect(head).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(screen.getByRole('button', { name: /read_file a\.py/ }))
  expect(screen.getByText('{"path":"a.py"}')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /list_dir \./ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /read_file gone\.py.*failed/ })).toBeInTheDocument()
  await userEvent.click(head)
  expect(screen.queryByText('read_file a.py')).not.toBeInTheDocument()
})

test('a line left open stays open when the chat is shown again', async () => {
  const state = looksAround('b', [
    ['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
    ['2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'],
  ])
  const { unmount } = render(<MessageList {...handlers} state={state} />)
  await userEvent.click(screen.getByRole('button', { name: /^Read 2 files/ }))
  unmount()
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('button', { name: /^Read 2 files/ })).toHaveAttribute('aria-expanded', 'true')
})

test('an open line split by a call that asks stays open on both sides; closed lines joined again open with the open one', async () => {
  const calls = (third: Parameters<typeof toolCall>[]) => [
    ['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
    ['2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'],
    ...third,
    ['4', 'r', 'list_dir', 'succeeded', '{}'],
    ['5', 'r', 'list_dir', 'succeeded', '{"path":"docs"}'],
  ] as Parameters<typeof toolCall>[]
  // (a call that has not asked yet: one of a batch, not started)
  const { rerender } = render(<MessageList {...handlers} state={looksAround('c', calls([['3', 'r', 'read_file', 'pending', '{"path":"c.py"}']]))} />)
  await userEvent.click(screen.getByRole('button', { name: /5 calls/ }))
  rerender(<MessageList {...handlers} state={looksAround('c', calls([['3', 'r', 'read_file', 'pending', '{"path":"D:/x/n.md"}', OUTSIDE]]))} />)
  expect(screen.getByRole('button', { name: 'Read 2 files, 2 calls, done' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: 'Listed 2 folders, 2 calls, done' })).toHaveAttribute('aria-expanded', 'true')
  cleanup()

  // A line left open that becomes part of a longer one, its other calls never opened: open.
  const later = looksAround('d', calls([['3', 'r', 'read_file', 'succeeded', '{"path":"c.py"}']]))
  render(<MessageList {...handlers} state={{ ...later, toolCalls: later.toolCalls.filter(call => call.id === 'ml-d4' || call.id === 'ml-d5') }} />)
  await userEvent.click(screen.getByRole('button', { name: /^Listed 2 folders/ }))
  cleanup()
  render(<MessageList {...handlers} state={later} />)
  expect(screen.getByRole('button', { name: /5 calls/ })).toHaveAttribute('aria-expanded', 'true')
})

test('a call you decided keeps its own row afterwards: an approved command runs in sight, not folded into a line', () => {
  const state = (status: 'proposed' | 'running') =>
    looksAround('e', [
      ['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
      ['2', 'r', 'run_command', status === 'proposed' ? 'pending' : 'running', '{"command":"pytest -q"}'],
      ['3', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'],
    ], { commands: [command('k', 'r', { tool_call_id: 'ml-e2', status, exit_code: null, ended_at: null })] })
  const { rerender } = render(<MessageList {...handlers} state={state('proposed')} />)
  expect(screen.getByRole('button', { name: /Run once|Allow once|Approve/ })).toBeInTheDocument()
  rerender(<MessageList {...handlers} state={state('running')} />)
  expect(screen.queryByRole('button', { name: /calls/ })).not.toBeInTheDocument()
  expect(screen.getByText('pytest -q')).toBeInTheDocument()
})

test('a line where nothing was done is read by its marks', () => {
  render(
    <MessageList
      {...handlers}
      state={looksAround('f', [
        ['1', 'r', 'read_file', 'failed', '{"path":"gone.py"}'],
        ['2', 'r', 'write_file', 'denied', '{"path":"b.py"}'],
      ])}
    />,
  )
  const head = screen.getByRole('button', { name: '1 failed, 1 rejected, 2 calls, failed' })
  expect(head).toHaveTextContent('1 rejected')
})

test('while the line runs it says what runs now', () => {
  const state = looksAround('g', [
    ['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
    ['2', 'r', 'read_file', 'running', '{"path":"cart.py"}'],
  ])
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('button', { name: 'Read 1 file · now: read_file cart.py, 2 calls, running' })).toBeInTheDocument()
})

test('a call that asks you is never inside a line: it splits the line, and its card is in view', () => {
  const state = looksAround('h', [
    ['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'],
    ['2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'],
    ['3', 'r', 'read_file', 'pending', '{"path":"D:/x/notes.md"}', { started_at: '2026-10-05T10:00:02Z', outside_folder: 'D:\\x' }],
    ['4', 'r', 'list_dir', 'succeeded', '{}'],
    ['5', 'r', 'list_dir', 'succeeded', '{"path":"docs"}'],
    ['6', 'r', 'run_command', 'succeeded', '{"command":"pytest -q"}'],
  ])
  render(<MessageList {...handlers} state={{ ...state, commands: [command('k', 'r', { tool_call_id: 'ml-h6' })] }} />)
  expect(screen.getByRole('button', { name: 'Read 2 files, 2 calls, done' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Allow once' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Listed 2 folders, ran 1 command, 3 calls, done' })).toBeInTheDocument()
})

test('a single call stays a row of its own', () => {
  render(<MessageList {...handlers} state={looksAround('i', [['1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}']])} />)
  expect(screen.getByRole('button', { name: /read_file a\.py/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /calls/ })).not.toBeInTheDocument()
})

test('what KOLONİ told the lead the same, several times in a row, is one line with ×N; the user’s and the lead’s words never are', () => {
  const WORDS = 'Its source changed since this turn began.'
  const told = (id: string) => ({ ...assistantMessage(id, 'r', WORDS), role: 'memory' as const })
  const messages: Message[] = [
    userMessage('r', 'again'),
    assistantMessage('a1', 'r', 'Same words.'),
    assistantMessage('a2', 'r', 'Same words.'),
    told('t1'),
    told('t2'),
    told('t3'),
    assistantMessage('a3', 'r', 'Done.'),
  ]
  render(<MessageList {...handlers} state={convState({ runs: [run('r', 'completed')], messages })} />)
  const notes = screen.getAllByRole('note', { name: 'Told by KOLONİ about its memory' })
  expect(notes).toHaveLength(1)
  expect(notes[0]).toHaveTextContent('told by KOLONİ, about what it was given from memory ×3')
  expect(screen.getAllByText('Same words.')).toHaveLength(2)
})
