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
  expect(within(menu).getByRole('radio', { name: 'Auto-edit files' })).toBeChecked()
  expect(within(menu).getByRole('radio', { name: 'Ask before changes' })).toHaveAccessibleDescription('Each file change and command waits for your card')
  expect(within(menu).getByRole('radio', { name: 'Full auto' })).toHaveAccessibleDescription('Changes and commands run; only harmful or risky actions ask')
  await userEvent.click(within(menu).getByRole('radio', { name: 'Full auto' }))
  expect(onMode).toHaveBeenCalledWith('full_auto')
  await userEvent.click(within(menu).getByRole('switch', { name: 'Plan first' }))
  expect(onPlanFirst).toHaveBeenCalledWith(true)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Permission level' })).toBeNull()
  expect(button).toHaveFocus()
})

test('without a conversation to set it on, the menu has no Plan first', async () => {
  render(<LevelMenu mode="ask" onMode={vi.fn()} planFirst={false} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Ask before changes' }))
  expect(screen.queryByRole('switch', { name: 'Plan first' })).toBeNull()
})
