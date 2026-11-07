import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { DiffView } from './DiffView'
import { languageOf } from './highlight'

const numbered = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => ` line ${from + i}`)
/** A file of 30 lines, its 15th changed: all of it, as the server sends it when asked (slice 42a). */
const whole = ['--- a/a.txt', '+++ b/a.txt', '@@ -1,30 +1,30 @@', ...numbered(1, 14), '-line 15', '+line fifteen', ...numbered(16, 30)].join('\n')
/** The same change as events carry it: three lines around it. */
const hunks = ['--- a/a.txt', '+++ b/a.txt', '@@ -12,7 +12,7 @@', ...numbered(12, 14), '-line 15', '+line fifteen', ...numbered(16, 18)].join('\n')
const rowOf = (text: string) => screen.getByText(text).closest('.diff-row, .diff-line')!

test('an added and a removed line say so in words too, not only in colour: a sign, and "added" / "removed" for a screen reader', () => {
  render(<DiffView diff={whole} />)
  expect(rowOf('line 15')).toHaveClass('diff-del')
  expect(rowOf('line 15')).toHaveTextContent(/^15−removed line 15$/)
  expect(rowOf('line fifteen')).toHaveTextContent(/^15\+added line fifteen$/)
  expect(screen.getByText('added')).toHaveClass('visually-hidden')
  expect(screen.getByText('removed')).toHaveClass('visually-hidden')
})

test('long runs that did not change are folded, three lines kept beside the change; a fold opens', async () => {
  render(<DiffView diff={whole} />)
  // 1-11 folded, 12-14 shown; 16-18 shown, 19-30 folded
  expect(screen.queryByText('line 11')).not.toBeInTheDocument()
  expect(screen.getByText('line 12')).toBeInTheDocument()
  expect(screen.getByText('line 18')).toBeInTheDocument()
  expect(screen.queryByText('line 19')).not.toBeInTheDocument()
  const first = screen.getByRole('button', { name: '11 unchanged lines' })
  expect(screen.getByRole('button', { name: '12 unchanged lines' })).toBeInTheDocument()
  await userEvent.click(first)
  expect(screen.getByText('line 1')).toBeInTheDocument()
  // the focus, which was on the fold, is on the first line it showed
  expect(rowOf('line 1')).toHaveFocus()
  expect(screen.getByText('line 11')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '11 unchanged lines' })).not.toBeInTheDocument()
  expect(screen.queryByText('line 19')).not.toBeInTheDocument()
})

test('side by side: before on the left, after on the right, on one row, each with its own line number', () => {
  const { container } = render(<DiffView diff={whole} split />)
  expect(container.querySelector('.diff-split')).not.toBeNull()
  const row = rowOf('line 15')
  expect(row).toContainElement(screen.getByText('line fifteen'))
  const [left, right] = Array.from(row.querySelectorAll('.diff-half'))
  expect(left).toHaveClass('diff-del')
  expect(left).toHaveTextContent(/^15−removed line 15$/)
  expect(right).toHaveClass('diff-add')
  expect(right).toHaveTextContent(/^15\+added line fifteen$/)
  // an unchanged line is on both sides
  expect(screen.getAllByText('line 14')).toHaveLength(2)
  // a line only added has nothing across from it
  render(<DiffView diff={['@@ -1,1 +1,2 @@', ' one', '+two'].join('\n')} split />)
  const [, empty] = Array.from(rowOf('two').querySelectorAll('.diff-half'))
  expect(rowOf('two').querySelector('.diff-half')).toHaveClass('diff-none')
  expect(empty).toHaveClass('diff-add')
})

test('what lies between the changes as they are sent is counted; a click reads the whole file and shows it, or says why not', async () => {
  const readWhole = vi.fn(async () => whole)
  const { unmount } = render(<DiffView diff={hunks} readWhole={readWhole} />)
  expect(screen.queryByText('line 11')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '11 unchanged lines' }))
  expect(readWhole).toHaveBeenCalledOnce()
  expect(await screen.findByText('line 1')).toBeInTheDocument()
  expect(screen.getByText('line 11')).toBeInTheDocument()
  expect(rowOf('line 1')).toHaveFocus()
  // the rest of the file, read now, is folded as a whole file is
  await userEvent.click(screen.getByRole('button', { name: '12 unchanged lines' }))
  expect(screen.getByText('line 30')).toBeInTheDocument()
  expect(readWhole).toHaveBeenCalledOnce()
  unmount()
  const refused = vi.fn(async () => Promise.reject(new Error('the file is too large to show whole')))
  const second = render(<DiffView diff={hunks} readWhole={refused} />)
  await userEvent.click(screen.getByRole('button', { name: '11 unchanged lines' }))
  expect(await screen.findByText('the file is too large to show whole')).toBeInTheDocument()
  expect(screen.queryByText('line 1')).not.toBeInTheDocument()
  second.unmount()
  // where nothing can read the file, the count is there, not a button
  render(<DiffView diff={hunks} />)
  expect(screen.getByText('11 unchanged lines')).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  render(<DiffView diff="" />)
  expect(screen.getByText('No textual difference.')).toBeInTheDocument()
})

test('code is coloured by the language its name says; an unknown one is plain text; what is coloured is never run', () => {
  const { container, unmount } = render(<DiffView diff={['@@ -0,0 +1,2 @@', '+def f():', '+    return "x"'].join('\n')} path="src/a.py" />)
  expect(container.querySelector('.hljs-keyword')).toHaveTextContent('def')
  expect(container.querySelector('.hljs-string')).toHaveTextContent('"x"')
  unmount()
  const page = render(<DiffView diff={['@@ -0,0 +1 @@', '+<script>window.ran = 1</script><svg onload="window.ran = 2"></svg>'].join('\n')} path="p.html" />)
  expect(page.container.querySelector('script, svg')).toBeNull()
  expect(page.container.querySelector('.hljs-tag')).not.toBeNull()
  expect(page.container.querySelector('.diff-add .diff-text')).toHaveTextContent('<script>window.ran = 1</script>')
  page.unmount()
  const plain = render(<DiffView diff={['@@ -0,0 +1 @@', '+def <b>f</b>'].join('\n')} path="notes.txt" />)
  expect(plain.container.querySelector('[class^="hljs"], b')).toBeNull()
  expect(screen.getByText('def <b>f</b>')).toBeInTheDocument()
})

test('a string over several lines is coloured on each of them, on each side apart (K-42a)', () => {
  const diff = ['@@ -1,4 +1,4 @@', ' x = """one', '-two < three', '+two <b>', ' four"""', ' y = 1'].join('\n')
  const { container } = render(<DiffView diff={diff} path="a.py" split />)
  const [before, after] = [0, 1].map(side => Array.from(container.querySelectorAll('.diff-row'), row => row.querySelectorAll('.diff-half')[side]))
  for (const half of [...before.slice(0, 3), ...after.slice(0, 3)]) expect(half.querySelector('.hljs-string')).not.toBeNull()
  // after it closes, code again; what is coloured is escaped
  expect(before[3].querySelector('.hljs-string')).toBeNull()
  expect(before[1]).toHaveTextContent('two < three')
  expect(after[1].querySelector('b')).toBeNull()
})

test('a name that is not a language is plain text, whatever it is called', () => {
  expect(languageOf('a.constructor')).toBeNull()
  expect(languageOf('x.__proto__')).toBeNull()
  render(<DiffView diff={['@@ -0,0 +1 @@', '+toString'].join('\n')} path="a.constructor" />)
  expect(screen.getByText('toString')).toBeInTheDocument()
})

test('a file over 5 000 lines is not coloured, and says so - counted by the file, not by what is shown of it; nor is a line over 2 000 characters', () => {
  const far = render(<DiffView diff={['@@ -6000,2 +6000,2 @@', ' x = 1', '-y = 2', '+y = 3'].join('\n')} path="far.py" />)
  expect(screen.getByText('plain text, file too large to colour')).toBeInTheDocument()
  expect(far.container.querySelector('[class^="hljs"]')).toBeNull()
  far.unmount()
  const long = render(<DiffView diff={['@@ -0,0 +1,2 @@', '+import os', `+x = "${'a'.repeat(2001)}"`].join('\n')} path="long.py" />)
  expect(long.container.querySelector('.hljs-keyword')).toHaveTextContent('import')
  expect(long.container.querySelector('.hljs-string')).toBeNull()
  long.unmount()

  const big = ['@@ -0,0 +1,5001 @@', ...Array.from({ length: 5001 }, (_, i) => `+x = ${i}`)].join('\n')
  const { container } = render(<DiffView diff={big} path="big.py" />)
  expect(screen.getByText('plain text, file too large to colour')).toBeInTheDocument()
  expect(container.querySelector('[class^="hljs"]')).toBeNull()
})
