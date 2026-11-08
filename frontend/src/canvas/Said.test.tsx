import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactFlowProvider } from '@xyflow/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { ChannelMessage } from '../api/types'
import { SaidBox } from './Said'
import { saidSide } from './saidSide'

const said = (id: string, from: string, kind: ChannelMessage['kind'], content: string): ChannelMessage => ({
  id,
  run_id: 'r',
  from_agent_id: from,
  to_agent_id: from === 'wl' ? 'dl' : 'wl',
  kind,
  content,
  created_at: '2026-11-05T10:00:00Z',
})

test('the user’s (5 Nov): who said what reads as a conversation - a bubble each, the two sides apart, a reply and findings tagged, a long one cut with “more”', async () => {
  const onClose = vi.fn()
  const long = 'x'.repeat(260)
  render(
    <ReactFlowProvider>
      <SaidBox
        position="top-left"
        title="Web app coordinator ↔ Data coordinator"
        said={[said('1', 'wl', 'message', 'Which table?'), said('2', 'dl', 'reply', long), said('3', 'dl', 'findings', '- no index on items | kind: code | role: Coder\n- slow join | kind: code | role: Coder')]}
        nameOf={id => ({ wl: 'Web app coordinator', dl: 'Data coordinator' })[id] ?? id}
        colourOf={() => 'hsl(200 65% 48%)'}
        right={m => m.from_agent_id === 'dl'}
        onClose={onClose}
      />
    </ReactFlowProvider>,
  )
  const box = screen.getByRole('region', { name: 'What was said' })
  expect(within(box).getByText('Web app coordinator ↔ Data coordinator')).toBeInTheDocument()
  const bubbles = within(box).getAllByRole('listitem').filter(li => li.classList.contains('said-bubble'))
  expect(bubbles.map(b => [b.querySelector('b')!.textContent, b.classList.contains('said-right'), b.querySelector('.tag')?.textContent ?? null])).toEqual([
    ['Web app coordinator', false, null],
    ['Data coordinator', true, 'reply'],
    ['Data coordinator', true, 'findings'],
  ])
  // findings a list; a long message cut, and whole on "more"
  expect(within(bubbles[2]).getAllByRole('listitem').map(li => li.textContent)).toEqual(['no index on items', 'slow join'])
  expect(bubbles[1]).toHaveTextContent(`${'x'.repeat(200)}…`)
  await userEvent.click(within(bubbles[1]).getByRole('button', { name: 'more' }))
  expect(bubbles[1]).toHaveTextContent(long)
  expect(within(bubbles[1]).getByRole('button', { name: 'less' })).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(within(box).getByRole('button', { name: 'Close what was said' }))
  expect(onClose).toHaveBeenCalled()
})

// --- where it opens, and moved (the user's, 6 Nov) ------------------------------------------------

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
})

/** What jsdom does not lay out: each element matching a selector at [left, top, width, height]; the rest the stage. */
function laidOut(at: Record<string, [number, number, number, number]>) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const [x, y, width, height] = Object.entries(at).find(([selector]) => this.matches(selector))?.[1] ?? [0, 0, 1000, 700]
    return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}) } as DOMRect
  })
}

test('it opens on the canvas’s right, under the Teams button and above the buttons at its foot - else where it opened before', () => {
  for (const name of ['react-flow', 'chat-teams', 'react-flow__controls', 'chat']) document.body.append(Object.assign(document.createElement('div'), { className: name }))
  const canvas: [number, number, number, number] = [0, 0, 1000, 700]
  const [teams, chat] = [[900, 14, 86, 36], [14, 400, 420, 286]] as [number, number, number, number][]
  laidOut({ '.react-flow': canvas, '.chat-teams': teams, '.react-flow__controls': [950, 450, 36, 235], '.chat': chat })
  // Its right edge the button's, 8px under it.
  expect(saidSide()).toEqual({ position: 'top-right', style: { marginTop: 58, marginRight: 14 } })
  // The chat put at the top right: the top left, as before.
  laidOut({ '.react-flow': canvas, '.chat-teams': teams, '.react-flow__controls': [950, 450, 36, 235], '.chat': [600, 0, 400, 300] })
  expect(saidSide()).toEqual({ position: 'top-left' })
  // Too short between the Teams button and the buttons: its foot, the chat being at the top left.
  laidOut({ '.react-flow': canvas, '.chat-teams': teams, '.react-flow__controls': [950, 300, 36, 235], '.chat': [14, 14, 420, 300] })
  expect(saidSide()).toEqual({ position: 'bottom-left' })
})

test('dragged by its head it goes where it is put, inside the canvas, and is there again next time; its grip moves it with the arrow keys; Close still closes', async () => {
  laidOut({ '.canvas-said': [600, 58, 360, 200] })
  const onClose = vi.fn()
  const box = () => screen.getByRole('region', { name: 'What was said' })
  const shown = () => (
    <ReactFlowProvider>
      <SaidBox position="top-right" title="What Coder said" said={[said('1', 'wl', 'message', 'Hi')]} nameOf={id => id} colourOf={() => 'red'} right={() => false} onClose={onClose} />
    </ReactFlowProvider>
  )
  const { unmount } = render(shown())
  const head = box().querySelector('.canvas-said-head')!
  expect(box()).not.toHaveClass('moved')
  fireEvent.pointerDown(head, { pointerId: 1, button: 0, clientX: 700, clientY: 70 })
  fireEvent.pointerMove(head, { pointerId: 1, clientX: 500, clientY: 170 })
  fireEvent.pointerUp(head, { pointerId: 1 })
  expect(box()).toHaveClass('moved')
  // Its left 400px in, its foot 342px up the 700px canvas.
  expect([box().style.getPropertyValue('--x'), box().style.getPropertyValue('--y')]).toEqual(['400px', '342px'])
  // Never out of the canvas.
  fireEvent.pointerDown(head, { pointerId: 2, button: 0, clientX: 700, clientY: 70 })
  fireEvent.pointerMove(head, { pointerId: 2, clientX: 5000, clientY: -5000 })
  fireEvent.pointerUp(head, { pointerId: 2 })
  expect([box().style.getPropertyValue('--x'), box().style.getPropertyValue('--y')]).toEqual(['640px', '500px'])
  unmount()
  render(shown())
  expect(box().style.getPropertyValue('--x')).toBe('640px')
  fireEvent.keyDown(within(box()).getByRole('button', { name: 'Move this box' }), { key: 'ArrowDown' })
  expect(box().style.getPropertyValue('--y')).toBe('484px')
  await userEvent.click(within(box()).getByRole('button', { name: 'Close what was said' }))
  expect(onClose).toHaveBeenCalled()
  expect(box().style.getPropertyValue('--y')).toBe('484px')
})
