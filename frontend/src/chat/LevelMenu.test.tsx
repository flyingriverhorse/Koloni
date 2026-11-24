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
  expect(within(menu).getByRole('menuitemradio', { name: 'Ask before changes' })).toHaveAccessibleDescription(
    'Each file change and command waits for your card',
  )
  expect(within(menu).getByRole('menuitemradio', { name: 'Full auto' })).toHaveAccessibleDescription(
    'Changes and commands run; only harmful or risky actions ask',
  )
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
  expect(screen.getByRole('button', { name: 'Permission level: Auto-edit files, Plan first on' })).toHaveTextContent(
    /^Auto-edit · plan$/,
  )
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
  const { unmount } = render(
    <LevelMenu
      mode="full_auto"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checkFirst={false}
      onCheckFirst={onCheckFirst}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Full auto' }))
  const check = screen.getByRole('switch', { name: 'Check what I said first' })
  expect(check).not.toBeChecked()
  expect(check).toHaveAccessibleDescription(
    /your own words are read first; it runs without a card only where a line of yours names it/,
  )
  await userEvent.click(check)
  expect(onCheckFirst).toHaveBeenCalledWith(true)
  unmount()
  render(<LevelMenu mode="full_auto" onMode={vi.fn()} planFirst={false} checkFirst />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Full auto' }))
  expect(screen.queryByRole('switch', { name: 'Check what I said first' })).toBeNull()
})

test('Test and review changes: a switch beside Plan first that saves the chat’s choice against the project’s', async () => {
  const onChange = vi.fn()
  const { rerender } = render(
    <LevelMenu
      mode="auto_edit"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: null, project: 'check', onChange }}
    />,
  )
  expect(screen.getByRole('button', { name: 'Permission level: Auto-edit files' })).toHaveTextContent(/^Auto-edit$/)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Auto-edit files' }))
  const row = screen.getByRole('switch', { name: 'Test and review changes' })
  expect(row).toBeChecked()
  expect(row).toHaveAccessibleDescription(
    'As the project: runs python -m pytest -q after each change, then a Reviewer reads big or security changes. Failing work goes back to be fixed, up to 2 times.',
  )
  await userEvent.click(row)
  expect(onChange).toHaveBeenLastCalledWith('off')
  // (Off for this chat: said against the project's, and on the level's button.)
  rerender(
    <LevelMenu
      mode="auto_edit"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: 'off', project: 'check', onChange }}
    />,
  )
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).not.toBeChecked()
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toHaveAccessibleDescription(
    'Off for this chat: nothing is tested or reviewed; each answer says “Not checked”.',
  )
  expect(screen.getByRole('button', { name: 'Permission level: Auto-edit files, no checks' })).toHaveTextContent(
    /^Auto-edit · no checks$/,
  )
  await userEvent.click(screen.getByRole('switch', { name: 'Test and review changes' }))
  expect(onChange).toHaveBeenLastCalledWith(null) // (back to the project's, which checks)
  // (In a project at Nothing, on is this chat's own word.)
  rerender(
    <LevelMenu
      mode="auto_edit"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: null, project: 'nothing', onChange }}
    />,
  )
  await userEvent.click(screen.getByRole('switch', { name: 'Test and review changes' }))
  expect(onChange).toHaveBeenLastCalledWith('on')
  rerender(
    <LevelMenu
      mode="auto_edit"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: 'on', project: 'nothing', onChange }}
    />,
  )
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toHaveAccessibleDescription(
    "On for this chat · the project's is Nothing: runs python -m pytest -q after each change, then a Reviewer reads big or security changes. Failing work goes back to be fixed, up to 2 times.",
  )
})

test('at Full auto with checks off, one line says so - the switch stays free', async () => {
  const onChange = vi.fn()
  const { rerender } = render(
    <LevelMenu
      mode="full_auto"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: 'off', project: 'check', onChange }}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Full auto, no checks' }))
  expect(screen.getByText('Full auto with no checks: nothing checks this chat’s changes')).toBeInTheDocument()
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toBeEnabled()
  rerender(
    <LevelMenu
      mode="full_auto"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'python -m pytest -q', rounds: 2, chat: null, project: 'check', onChange }}
    />,
  )
  expect(screen.queryByText('Full auto with no checks: nothing checks this chat’s changes')).toBeNull()
})

test('a plain chat has no Test and review changes', async () => {
  render(<LevelMenu mode="ask" onMode={vi.fn()} planFirst={false} onPlanFirst={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Ask before changes' }))
  expect(screen.queryByRole('switch', { name: 'Test and review changes' })).toBeNull()
})

test('the switch’s line: Tests only runs with no review, Nothing as the project runs nothing; its ⓘ is the guide’s Checked page', async () => {
  const onChange = vi.fn()
  const { rerender } = render(
    <LevelMenu
      mode="ask"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'npm test', rounds: 1, chat: null, project: 'tests', onChange }}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Permission level:/ }))
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toHaveAccessibleDescription(
    'As the project: runs npm test after each change. Failing work goes back to be fixed, up to 1 time.',
  )
  rerender(
    <LevelMenu
      mode="ask"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'npm test', rounds: null, chat: null, project: 'tests', onChange }}
    />,
  )
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toHaveAccessibleDescription(
    'As the project: runs npm test after each change. Failing work goes back to be fixed, until it passes, while each round makes progress.',
  )
  rerender(
    <LevelMenu
      mode="ask"
      onMode={vi.fn()}
      planFirst={false}
      onPlanFirst={vi.fn()}
      checks={{ command: 'npm test', rounds: 1, chat: null, project: 'nothing', onChange }}
    />,
  )
  expect(screen.getByRole('switch', { name: 'Test and review changes' })).toHaveAccessibleDescription(
    'As the project: nothing is tested or reviewed; each answer says “Not checked”.',
  )
  await userEvent.click(screen.getByRole('button', { name: /more about|ⓘ|about this/i }))
  expect(screen.getByRole('link', { name: /learn more/i })).toHaveAttribute(
    'href',
    expect.stringContaining('use/checked/'),
  )
})
