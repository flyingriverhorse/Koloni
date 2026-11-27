import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { stamp } from '../ready/decisionLog'
import { NotebookButton } from './Notebook'

const note = (kind: string, text: string, by: string) => ({ kind, text, by, at: '2026-11-24T10:00:00Z' })

const AT = stamp('2026-11-24T10:00:00Z')

test('📓 4 notes opens the notebook: each note with its kind, who wrote it and when, as written', async () => {
  const story = {
    title: 'Şifre sıfırlama',
    notes: [
      note('decision', 'mail by SMTP', 'Hive keeper'),
      note('file', '“mail” changed mail.py', 'KOLONİ'),
      note('result', '“mail” — done?', 'KOLONİ'),
      note('question', 'which sender address?', 'Orchestrator'),
    ],
  }
  render(<NotebookButton story={story} />)
  await userEvent.click(screen.getByRole('button', { name: '4 notes' }))
  const lines = screen.getAllByRole('listitem').map(line => line.textContent)
  expect(lines).toEqual([
    `Decision mail by SMTP · Hive keeper · ${AT}`,
    `File “mail” changed mail.py · KOLONİ · ${AT}`,
    `Result “mail” — done? · KOLONİ · ${AT}`,
    `Question which sender address? · Orchestrator · ${AT}`,
  ])
})

test('no button while the notebook is empty; one note says so; a label stands for the count', () => {
  const { rerender } = render(<NotebookButton story={{ title: 's', notes: [] }} />)
  expect(screen.queryByRole('button')).toBeNull()
  rerender(<NotebookButton story={{ title: 's', notes: [note('result', 'r', 'KOLONİ')] }} />)
  expect(screen.getByRole('button', { name: '1 note' })).toBeVisible()
  rerender(<NotebookButton story={{ title: 's', notes: [note('result', 'r', 'KOLONİ')] }} label="notes" />)
  expect(screen.getByRole('button', { name: 'notes' })).toHaveAttribute('aria-expanded', 'false')
})

test('0.1.10: a task’s notebook says it is the task’s, and a note left for the whole turn is a Note', async () => {
  render(
    <NotebookButton
      story={{ title: 'fix the parser', notes: [note('note', 'parser in app/parse.py', 'Coder')] }}
      of="task"
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: '1 note' }))
  expect(screen.getByRole('dialog', { name: 'Notebook of fix the parser' })).toHaveTextContent(
    'Given to every turn of the task, as data.',
  )
  expect(screen.getByRole('listitem')).toHaveTextContent('Note parser in app/parse.py · Coder')
})
