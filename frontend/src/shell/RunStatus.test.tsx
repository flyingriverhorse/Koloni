import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { agent, convState, question, run } from '../test-fixtures'
import { RunStatus } from './RunStatus'

test('a turn waiting on a question waits for you: how many, and the way there, is the top bar’s Ready pill (tek-ev §1)', () => {
  const conv = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r')],
    questions: [question('q', 'r')],
  })
  const { container } = render(<RunStatus conv={conv} connection="open" />)
  // (The dot in the warning colour; the words are the pill’s, so the top bar says “waits” once.)
  expect(container.querySelector('.tag-warn > .dot')).toBeInTheDocument()
  expect(screen.queryByText(/WAITS FOR YOU/)).toBeNull()
})

test('a turn waiting on something else is the same: the dot, no words', () => {
  const conv = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r')],
    questions: [question('q', 'r', { status: 'answered', answer: 'hey' })],
  })
  const { container } = render(<RunStatus conv={conv} connection="open" />)
  expect(container.querySelector('.tag-warn')).toHaveTextContent(/^$/)
})

// Slice 77a: how full the Lead's context is, as its window says it.
describe('the header says how full the lead’s context is', () => {
  test('of its window, where that is known', () => {
    const conv = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { input_tokens: 620, context_window: 1000 })] })
    render(<RunStatus conv={conv} connection="open" />)
    expect(screen.getByText('context 62%')).toBeInTheDocument()
  })

  test('its tokens where the window is not known; “–” for a CLI or with nothing measured, the button there all the same', () => {
    const conv = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { input_tokens: 12345 })] })
    const { unmount } = render(<RunStatus conv={conv} connection="open" />)
    expect(screen.getByText('context 12,345 tokens')).toBeInTheDocument()
    unmount()
    const cli = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { input_tokens: 12345, provider_mode: 'reads' })] })
    const { unmount: gone } = render(<RunStatus conv={cli} connection="open" />)
    expect(screen.getByRole('button', { name: 'context –' })).toBeInTheDocument()
    expect(screen.queryByText(/12,345/)).toBeNull() // (its count is not what it holds)
    gone()
    const none = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')] })
    const { unmount: away } = render(<RunStatus conv={none} connection="open" />)
    expect(screen.getByRole('button', { name: 'context –' })).toBeInTheDocument()
    away()
    // A lead that never started: nothing to open.
    const proposed = convState({ runs: [run('r', 'running')], agents: [agent('r', 'proposed', { started_at: null })] })
    expect(render(<RunStatus conv={proposed} connection="open" />).container.textContent).not.toMatch(/context/)
  })
})

// A CLI lead KOLONİ compacts (it starts each turn anew), and one that goes on in its session (compacts itself).
test('a CLI lead’s context opens with Compact now where KOLONİ compacts it, “compacts itself” where its session goes on', async () => {
  const lead = (compacts_itself: boolean) =>
    convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { provider_mode: 'native', provider_name: 'agy', compacts_itself })] })
  const { unmount } = render(<RunStatus conv={lead(false)} connection="open" />)
  await userEvent.click(screen.getByRole('button', { name: 'context –' }))
  const anew = screen.getByRole('dialog', { name: 'Each agent’s context' })
  expect(within(anew).getByRole('button', { name: 'Compact now' })).toBeInTheDocument()
  expect(within(anew).queryByText('compacts itself')).toBeNull()
  unmount()
  render(<RunStatus conv={lead(true)} connection="open" />)
  await userEvent.click(screen.getByRole('button', { name: 'context –' }))
  const resumes = screen.getByRole('dialog', { name: 'Each agent’s context' })
  expect(within(resumes).getByText('compacts itself')).toBeInTheDocument()
  expect(within(resumes).queryByRole('button', { name: 'Compact now' })).toBeNull()
})

test('a CLI lead run step by step says each step is sent a trimmed history, not that it compacts itself', async () => {
  const conv = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { provider_mode: 'step', compacts_itself: true })] })
  render(<RunStatus conv={conv} connection="open" />)
  await userEvent.click(screen.getByRole('button', { name: 'context –' }))
  const panel = screen.getByRole('dialog', { name: 'Each agent’s context' })
  expect(within(panel).getByText('each step is sent a trimmed history; not compacted')).toBeInTheDocument()
  expect(within(panel).queryByText('compacts itself')).toBeNull()
  expect(within(panel).queryByRole('button', { name: 'Compact now' })).toBeNull()
})

// K-baglam-paneli: the lead's context opens each agent's of the turn.
describe('the context in the top bar opens each agent’s', () => {
  afterEach(() => vi.unstubAllGlobals())
  const team = (leadStatus: ReturnType<typeof agent>['status'] = 'completed') =>
    convState({
      runs: [run('r', leadStatus === 'completed' ? 'completed' : 'running')],
      agents: [
        agent('r', leadStatus, { input_tokens: 620, context_window: 1000 }),
        agent('r', 'completed', { id: 's1', name: 'Coder', role_name: 'Coder', depth: 1, input_tokens: 4000 }),
        agent('r', 'completed', { id: 's2', name: 'Claude', role_name: 'Reviewer', depth: 1, provider_mode: 'native', compacts_itself: true, input_tokens: 9000 }),
        // Never started: not listed.
        agent('r', 'proposed', { id: 's3', name: 'Tester', role_name: 'Tester', depth: 1, started_at: null }),
      ],
    })
  const open = async () => userEvent.click(screen.getByRole('button', { name: 'context 62%' }))
  const row = (name: string) => screen.getByText(name).closest('li') as HTMLElement

  test('each agent with its % and in / window, unknown as “–”; a CLI compacts itself; Compact now only on a finished lead KOLONİ runs', async () => {
    const asked = vi.fn(async () => new Response(JSON.stringify(agent('r', 'completed', { summarised: 2 })), { status: 200 }))
    vi.stubGlobal('fetch', asked)
    render(<RunStatus conv={team()} connection="open" />)
    await open()
    const panel = screen.getByRole('dialog', { name: 'Each agent’s context' })
    expect(panel).toHaveFocus()
    expect(row('Lead')).toHaveTextContent('62%620 / 1,000')
    // The window not known: no % made up.
    expect(row('Coder')).toHaveTextContent('–4,000 / –')
    expect(row('Claude')).toHaveTextContent('–– / –')
    expect(within(row('Claude')).getByText('compacts itself')).toBeInTheDocument()
    expect(within(panel).getAllByRole('listitem')).toHaveLength(3)
    expect(within(panel).getAllByRole('button', { name: 'Compact now' })).toHaveLength(1)
    await userEvent.click(within(row('Lead')).getByRole('button', { name: 'Compact now' }))
    expect(asked).toHaveBeenCalledWith('/api/agents/r/compact', expect.objectContaining({ method: 'POST' }))
    expect(await within(panel).findByText('Compacted: 2 messages more summarised.')).toHaveAttribute('role', 'status')
  })

  test('while the lead is at work Compact now says why, and does nothing', async () => {
    const asked = vi.fn()
    vi.stubGlobal('fetch', asked)
    render(<RunStatus conv={team('running')} connection="open" />)
    await open()
    const button = within(row('Lead')).getByRole('button', { name: 'Compact now' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(/It is at work: it is compacted at its next step/)
    await userEvent.click(button)
    expect(within(row('Lead')).getByRole('status')).toHaveTextContent(/Compact it once its work is over/)
    expect(asked).not.toHaveBeenCalled()
  })

  test('Esc and a click outside close it, the focus back on its button', async () => {
    render(
      <>
        <button type="button">elsewhere</button>
        <RunStatus conv={team()} connection="open" />
      </>,
    )
    const trigger = screen.getByRole('button', { name: 'context 62%' })
    await open()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    await open()
    await userEvent.click(document.body)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
