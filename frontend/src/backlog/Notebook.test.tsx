import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { NotebookButton } from './Notebook'

const note = (kind: string, text: string, by: string) => ({ kind, text, by, at: '2026-11-24T10:00:00Z' })

test('📓 4 notes opens the notebook: each note with its kind and who wrote it, as written', async () => {
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
    'Decision mail by SMTP · Hive keeper',
    'File “mail” changed mail.py · KOLONİ',
    'Result “mail” — done? · KOLONİ',
    'Question which sender address? · Orchestrator',
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
