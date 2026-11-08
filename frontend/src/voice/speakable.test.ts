import { expect, test } from 'vitest'
import { firstTwo, sentences, speakable } from './speakable'

test('an answer is said by its words: a code block as "code block, N lines", a link by its name, no table, no address, no marks', () => {
  const answer = [
    '## The total',
    'It adds **20%** tax once, in `total()`: see [the tax rule](https://example.com/tax) or https://example.com/tax today.',
    '',
    '```python',
    'subtotal = 10',
    'total = subtotal * 1.2',
    '```',
    '',
    '| a | b |',
    '|---|---|',
    '- one item',
    '- ![a chart](chart.png) two',
  ].join('\n')
  expect(speakable(answer)).toBe('The total. It adds 20% tax once, in total(): see the tax rule or today. Code block, 2 lines. one item. two.')
  expect(speakable('```\nonly\n```')).toBe('Code block, 1 line.')
})

test('an answer still being written: an unclosed code block is not said, nor counted, until it closes', () => {
  expect(speakable('Here it is:\n```js\nlet a = 1\n', true)).toBe('Here it is.')
  expect(speakable('Here it is:\n```js\nlet a = 1\n')).toBe('Here it is. Code block, 1 line.')
})

test('sentences are finished once something follows their end; what is still being written waits', () => {
  expect(sentences('It adds the tax. Twenty percent! And the rest')).toEqual({ done: ['It adds the tax.', 'Twenty percent!'], rest: 'And the rest' })
  expect(sentences('Is it 1.2 times? Yes.')).toEqual({ done: ['Is it 1.2 times?'], rest: 'Yes.' })
})

test('the first two sentences of an answer are of its prose: a code block before them is not one', () => {
  expect(firstTwo('```py\nx = 1\n```\nFirst. Second. Third.')).toBe('First. Second.')
})
