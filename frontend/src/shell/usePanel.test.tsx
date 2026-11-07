import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { AllowList } from '../commands/AllowList'
import { ModelPicker } from '../models/ModelPicker'
import { usePanel } from './usePanel'

const local: Provider = {
  id: 'p1', name: 'Local', kind: 'openai_compat', base_url: 'http://x/v1', default_model: null, executable: null, mode: null, options: null,
  for_agents: true, note: null, models: [], only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't',
}

/** The panels of the row under the message box: the button that opens each, what the panel is called, and what it is. */
const PANELS: [button: string, panel: string, role: 'dialog' | 'form', draw: () => ReactNode][] = [
  ['Model: Local', 'Model for this conversation', 'form', () => <ModelPicker providers={[local]} providerId={null} modelId={null} onSave={vi.fn().mockResolvedValue(undefined)} />],
  ['0 rules', 'Runs without asking', 'dialog', () => <AllowList rules={[]} onRemove={vi.fn()} onAllowHost={vi.fn()} />],
]

afterEach(() => vi.restoreAllMocks())

test.each(PANELS)('the panel of "%s" opens with the focus in it; Esc, a click anywhere else and its own button close it, and the focus is back on that button', async (name, title, role, draw) => {
  render(
    <>
      <textarea aria-label="Message" />
      {draw()}
    </>,
  )
  const button = screen.getByRole('button', { name })
  const panel = () => screen.queryByRole(role, { name: title })
  expect(panel()).not.toBeInTheDocument()
  expect(button).toHaveAttribute('aria-expanded', 'false')

  await userEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  expect(panel()).toHaveFocus()
  // Esc: closed, and the focus is where it came from
  await userEvent.keyboard('{Escape}')
  expect(panel()).not.toBeInTheDocument()
  expect(button).toHaveFocus()
  expect(button).toHaveAttribute('aria-expanded', 'false')

  // a click in the panel is not a click anywhere else
  await userEvent.click(button)
  await userEvent.click(within(panel()!).getByText(title))
  expect(panel()).toBeInTheDocument()
  // a click on nothing in particular: closed, and the focus is back on the button
  await userEvent.click(document.body)
  expect(panel()).not.toBeInTheDocument()
  expect(button).toHaveFocus()

  // a click on something that takes the focus: closed, and the focus stays where the click put it
  await userEvent.click(button)
  await userEvent.click(screen.getByLabelText('Message'))
  expect(panel()).not.toBeInTheDocument()
  expect(screen.getByLabelText('Message')).toHaveFocus()

  // its own button closes it as it opened it
  await userEvent.click(button)
  expect(panel()).toBeInTheDocument()
  await userEvent.click(button)
  expect(panel()).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})

test('one panel at a time: opening another closes the one that was open', async () => {
  render(
    <>
      {PANELS[1][3]()}
      {PANELS[0][3]()}
    </>,
  )
  await userEvent.click(screen.getByRole('button', { name: '0 rules' }))
  expect(screen.getByRole('dialog', { name: 'Runs without asking' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Model: Local' }))
  expect(screen.queryByRole('dialog', { name: 'Runs without asking' })).not.toBeInTheDocument()
  expect(screen.getByRole('form', { name: 'Model for this conversation' })).toHaveFocus()
})

test('a panel that closes itself after a save gives the focus back too', async () => {
  render(PANELS[0][3]())
  const button = screen.getByRole('button', { name: 'Model: Local' })
  await userEvent.click(button)
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(screen.queryByRole('form', { name: 'Model for this conversation' })).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})

test('a panel stands over the row it opens from, from the row’s left end, and is given no more room than the window has', async () => {
  // (Nothing is laid out here: the row is said to be where it is in the app.)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const at = this.classList.contains('composer-row') ? { left: 66, top: 700, width: 380, height: 30 } : { left: 300, top: 700, width: 90, height: 30 }
    return { ...at, x: at.left, y: at.top, right: at.left + at.width, bottom: at.top + at.height, toJSON: () => at } as DOMRect
  })
  render(<div className="composer-row">{PANELS[0][3]()}</div>)
  await userEvent.click(screen.getByRole('button', { name: 'Model: Local' }))
  const panel = screen.getByRole('form', { name: 'Model for this conversation' })
  // its left edge is the row's, not its button's; its bottom is over the row; and it ends before the window does
  expect(panel.style.left).toBe('66px')
  expect(panel.style.bottom).toBe(`${window.innerHeight - 700 + 8}px`)
  expect(panel.style.maxWidth).toBe(`${window.innerWidth - 66 - 8}px`)
  expect(panel.style.maxHeight).toBe('684px')
})

test('a panel of the row under the message box stands over it even with the chat moved high; one elsewhere moves over or under its button as the window changes, never both', async () => {
  let rowTop = 100
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const at = { left: 66, top: rowTop, width: 380, height: 30 }
    return { ...at, x: at.left, y: at.top, right: at.left + at.width, bottom: at.top + at.height, toJSON: () => at } as DOMRect
  })
  const { unmount } = render(<div className="composer-row">{PANELS[0][3]()}</div>)
  await userEvent.click(screen.getByRole('button', { name: 'Model: Local' }))
  const over = screen.getByRole('form', { name: 'Model for this conversation' })
  expect(over.style.bottom).toBe(`${window.innerHeight - 100 + 8}px`)
  expect(over.style.top).toBe('')
  unmount()

  // (a button of no row: as Help and the legend are)
  render(PANELS[1][3]())
  await userEvent.click(screen.getByRole('button', { name: '0 rules' }))
  const panel = screen.getByRole('dialog', { name: 'Runs without asking' })
  expect(panel.style.top).toBe('138px')
  expect(panel.style.bottom).toBe('')
  rowTop = 700
  window.dispatchEvent(new Event('resize'))
  expect(panel.style.top).toBe('')
  expect(panel.style.bottom).toBe(`${window.innerHeight - 700 + 8}px`)
})

test("a panel opened from a button low at the window's right edge (the canvas's legend) stays inside the window", async () => {
  function Low() {
    const { open, setOpen, button, panel } = usePanel()
    return (
      <>
        <button ref={button} type="button" onClick={() => setOpen(true)}>
          Legend
        </button>
        {open && <div ref={panel} tabIndex={-1} role="dialog" aria-label="Legend" />}
      </>
    )
  }
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ left: 990, top: 700, right: 1016, bottom: 726, width: 26, height: 26, x: 990, y: 700, toJSON: () => ({}) } as DOMRect)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(380)
  render(<Low />)
  await userEvent.click(screen.getByRole('button', { name: 'Legend' }))
  const shown = screen.getByRole('dialog', { name: 'Legend' })
  // (above the button, as wide as it is, its right edge 8px inside the window's)
  expect(shown.style.left).toBe(`${window.innerWidth - 380 - 8}px`)
  expect(shown.style.bottom).toBe(`${window.innerHeight - 700 + 8}px`)
})

/** A panel that holds another (⚙ Chat's sheet, with a plain chat's list of what runs without asking). */
function Outer() {
  const { open, setOpen, close, button, panel } = usePanel()
  return (
    <div className="allow-list">
      <button ref={button} type="button" onClick={() => (open ? close() : setOpen(true))}>
        Outer
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Outer panel" className="allow-list-panel">
          <AllowList rules={[]} onRemove={vi.fn()} onAllowHost={vi.fn()} />
        </div>
      )}
    </div>
  )
}

test('Esc in a panel open inside another closes the inner one alone; the next Esc closes the outer one', async () => {
  render(<Outer />)
  await userEvent.click(screen.getByRole('button', { name: 'Outer' }))
  await userEvent.click(screen.getByRole('button', { name: '0 rules' }))
  expect(screen.getByRole('dialog', { name: 'Runs without asking' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Runs without asking' })).toBeNull()
  expect(screen.getByRole('dialog', { name: 'Outer panel' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '0 rules' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Outer panel' })).toBeNull()
})
