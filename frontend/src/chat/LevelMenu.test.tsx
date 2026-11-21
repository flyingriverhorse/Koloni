import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { LevelMenu } from './LevelMenu'

test('the level is three comb cells and its name; a click opens each level with a line on what it does, and Plan first', async () => {
  const onMode = vi.fn()
  const onPlanFirst = vi.fn()
  render(<LevelMenu mode="auto_edit" onMode={onMode} planFirst={false} onPlanFirst={onPlanFirst} />)
  const button = screen.getByRole('button', { name: 'Permission level: Auto-edit files' })
  expect(button).toHaveTextContent(/^Auto-edit$/)
  expect(button).toHaveAttribute('data-level', 'auto_edit')
  // (Two of its three cells filled: drawn, not read out.)
  expect(button.querySelectorAll('[data-cell="on"]')).toHaveLength(2)
  expect(button.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  await userEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  const menu = screen.getByRole('dialog', { name: 'Permission level' })
  expect(menu).toHaveFocus()
  expect(within(menu).getByRole('menuitemradio', { name: 'Auto-edit files' })).toBeChecked()
  expect(within(menu).getByRole('menuitemradio', { name: 'Ask before changes' })).toHaveAccessibleDescription('Each file change and command waits for your card')
  expect(within(menu).getByRole('menuitemradio', { name: 'Full auto' })).toHaveAccessibleDescription('Changes and commands run; only harmful or risky actions ask')
  await userEvent.click(within(menu).getByRole('menuitemradio', { name: 'Full auto' }))
  expect(onMode).toHaveBeenCalledWith('full_auto')
  await userEvent.click(within(menu).getByRole('switch', { name: 'Plan first' }))
  expect(onPlanFirst).toHaveBeenCalledWith(true)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Permission level' })).toBeNull()
  expect(button).toHaveFocus()
})

test('with Plan first on, the level says so on its button - "Auto-edit · plan", named "Plan first on" -; off, nothing more', () => {
  const { rerender } = render(<LevelMenu mode="auto_edit" onMode={vi.fn()} planFirst onPlanFirst={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Permission level: Auto-edit files, Plan first on' })).toHaveTextContent(/^Auto-edit · plan$/)
  rerender(<LevelMenu mode="auto_edit" onMode={vi.fn()} planFirst={false} onPlanFirst={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Permission level: Auto-edit files' })).toHaveTextContent(/^Auto-edit$/)
})

test('without a conversation to set it on, the menu has no Plan first', async () => {
  render(<LevelMenu mode="ask" onMode={vi.fn()} planFirst={false} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Ask before changes' }))
  expect(screen.queryByRole('switch', { name: 'Plan first' })).toBeNull()
})

test('the arrows move between the levels only; a level is chosen by a click, Enter or Space', async () => {
  const onMode = vi.fn()
  render(<LevelMenu mode="ask" onMode={onMode} planFirst={false} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Ask before changes' }))
  const menu = screen.getByRole('dialog', { name: 'Permission level' })
  within(menu).getByRole('menuitemradio', { name: 'Ask before changes' }).focus()
  await userEvent.keyboard('{ArrowUp}')
  // (No jump round to Full auto, nor any level chosen by moving.)
  expect(within(menu).getByRole('menuitemradio', { name: 'Ask before changes' })).toHaveFocus()
  await userEvent.keyboard('{ArrowDown}{ArrowDown}')
  expect(within(menu).getByRole('menuitemradio', { name: 'Full auto' })).toHaveFocus()
  expect(onMode).not.toHaveBeenCalled()
  await userEvent.keyboard('{Enter}')
  expect(onMode).toHaveBeenCalledWith('full_auto')
})

test('Check what I said first: a switch under the levels that saves the project’s check; none without a project', async () => {
  const onCheckFirst = vi.fn()
  const { unmount } = render(<LevelMenu mode="full_auto" onMode={vi.fn()} planFirst={false} onPlanFirst={vi.fn()} checkFirst={false} onCheckFirst={onCheckFirst} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Full auto' }))
  const check = screen.getByRole('switch', { name: 'Check what I said first' })
  expect(check).not.toBeChecked()
  expect(check).toHaveAccessibleDescription(/your own words are read first; it runs without a card only where a line of yours names it/)
  await userEvent.click(check)
  expect(onCheckFirst).toHaveBeenCalledWith(true)
  unmount()
  render(<LevelMenu mode="full_auto" onMode={vi.fn()} planFirst={false} checkFirst />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Full auto' }))
  expect(screen.queryByRole('switch', { name: 'Check what I said first' })).toBeNull()
})
