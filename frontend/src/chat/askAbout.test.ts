import { afterEach, describe, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { FileHistory } from '../api/types'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, convState } from '../test-fixtures'
import { linesIn, MOST_LINES, quoteOf, writerOf } from './askAbout'

afterEach(() => {
  resetStoreForTests()
  vi.restoreAllMocks()
})

const code = { path: 'app/x.py', from: 12, to: 18, text: 'def pay():\n    return 1\n' }

describe('the quote "Ask about this" puts into the message box', () => {
  test('the path and lines, then the text fenced', () => {
    expect(quoteOf(code, null)).toBe('app/x.py:12–18:\n```\ndef pay():\n    return 1\n```\n\n')
    // R125: on the branch it was read on, where the project is in git
    expect(quoteOf(code, { name: 'Coder', atWork: false }, 'feature-x')).toMatch(/^app\/x\.py:12–18 on feature-x \(Coder wrote this\):\n/)
  })

  test('who wrote it, and whether it is still working', () => {
    expect(quoteOf(code, { name: 'Coder', atWork: false })).toMatch(/^app\/x\.py:12–18 \(Coder wrote this\):\n/)
    expect(quoteOf(code, { name: 'Coder', atWork: true })).toMatch(/^app\/x\.py:12–18 \(Coder wrote this and is still working\):\n/)
  })

  test('one line; from a message, no place at all', () => {
    expect(quoteOf({ ...code, to: 12 }, null)).toMatch(/^app\/x\.py:12:\n/)
    expect(quoteOf({ path: null, from: null, to: null, text: 'use the banner' }, null)).toBe('```\nuse the banner\n```\n\n')
  })

  test('a fence in the text does not close the quote; a long one is cut, its lines kept', () => {
    expect(quoteOf({ ...code, text: 'say:\n```js\nx\n```' }, null)).toBe('app/x.py:12–18:\n````\nsay:\n```js\nx\n```\n````\n\n')
    const long = Array.from({ length: MOST_LINES + 5 }, (_, n) => `line ${n + 1}`).join('\n')
    const quote = quoteOf({ path: 'a.txt', from: 1, to: MOST_LINES + 5, text: long }, null)
    expect(quote).toMatch(/^a\.txt:1–65:\n/)
    expect(quote).toContain(`line ${MOST_LINES}\n\`\`\`\n(5 more lines not quoted)`)
    expect(quote).not.toContain(`line ${MOST_LINES + 1}`)
  })
})

/** Lines as the file view (one number) or a unified diff (old and new) draw them. */
function view(rows: [string[], string][]): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = rows
    .map(([numbers, text]) => `<div class="diff-line">${numbers.map(n => `<span class="diff-no">${n}</span>`).join('')}<span class="diff-sign">+</span><span class="diff-text">${text}</span></div>`)
    .join('')
  document.body.append(root)
  return root
}

const textOf = (root: HTMLElement, n: number) => root.querySelectorAll('.diff-text')[n].firstChild!

describe('the lines a selection covers', () => {
  test('whole lines by their text, never the numbers beside them', () => {
    const root = view([[['1'], 'a = 1'], [['2'], 'b = 2'], [['3'], 'c = 3']])
    const range = document.createRange()
    range.setStart(textOf(root, 0), 2)
    range.setEnd(textOf(root, 1), 3)
    expect(linesIn(root, range, range.toString())).toEqual({ from: 1, to: 2, text: 'a = 1\nb = 2' })
  })

  test('in a diff, the new side’s numbers; part of one line is that part', () => {
    const root = view([[['4', '4'], 'same'], [['5', ''], 'gone'], [['', '5'], 'added']])
    const range = document.createRange()
    range.setStart(textOf(root, 1), 0)
    range.setEnd(textOf(root, 2), 5)
    expect(linesIn(root, range, range.toString())).toEqual({ from: 5, to: 5, text: 'gone\nadded' })
    range.setStart(textOf(root, 2), 1)
    range.setEnd(textOf(root, 2), 4)
    expect(linesIn(root, range, range.toString())).toEqual({ from: 5, to: 5, text: 'dde' })
  })

  test('a selection that ends at the start of a line is of the lines before it; outside lines, its own text', () => {
    const root = view([[['1'], 'a = 1'], [['2'], 'b = 2']])
    const range = document.createRange()
    range.setStart(textOf(root, 0), 0)
    range.setEnd(root.children[1], 0)
    expect(linesIn(root, range, 'a = 1\n')).toEqual({ from: 1, to: 1, text: 'a = 1' })
    const words = document.createElement('p')
    words.textContent = 'use the banner'
    document.body.append(words)
    range.selectNodeContents(words)
    expect(linesIn(words, range, 'use the banner')).toEqual({ from: null, to: null, text: 'use the banner' })
  })
})

describe('who wrote the file', () => {
  const told = (over: Partial<FileHistory>): FileHistory => ({
    at: '2026-11-03T10:00:00Z', agent_id: 'w', agent_role: 'Coder', agent_name: 'Coder', conversation_id: 'c', conversation_title: 'x', kind: 'modify', status: 'taken in', ...over,
  })
  const history = (...found: FileHistory[]) => vi.spyOn(api, 'get').mockResolvedValue(found)

  test('the last change on record, taken in or waiting: its agent, at work if it is in this chat and working', async () => {
    useApp.setState({ projectId: 'p', conv: convState({ agents: [agent('w', 'running')] }) })
    const read = history(told({}), told({ agent_id: 'old', agent_role: 'Tester' }))
    expect(await writerOf('app/x.py')).toEqual({ name: 'Coder', atWork: true })
    expect(read).toHaveBeenCalledWith('/projects/p/file-history?path=app%2Fx.py')
    history(told({ status: 'waiting', agent_id: 'elsewhere', agent_role: 'Lead' }))
    // (an agent of another chat is not known to be at work here; the Lead is the Orchestrator)
    expect(await writerOf('app/x.py')).toEqual({ name: 'Orchestrator', atWork: false })
  })

  test('none where the last change was discarded, or there is none on record', async () => {
    useApp.setState({ projectId: 'p' })
    history(told({ status: 'discarded' }), told({}))
    expect(await writerOf('app/x.py')).toBeNull()
    vi.spyOn(api, 'get').mockResolvedValue(null)
    expect(await writerOf('app/x.py')).toBeNull()
  })
})
