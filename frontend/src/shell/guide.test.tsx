import { readFileSync } from 'node:fs'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { GUIDE } from './guide'
import { Hint } from './Hint'

/** A heading's anchor as Zensical makes it (Python-Markdown's slugify; checked once against a built site). */
const slug = (heading: string) =>
  heading
    .replace(/[*`]/g, '')
    .normalize('NFKD')
    .replace(/[\u0080-￿]/g, '')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .toLowerCase()
    .replace(/[-\s]+/g, '-')

test.each(Object.entries(GUIDE))('%s: the guide has %s', (_name, place) => {
  const [page, anchor] = place.split('#')
  // (run from frontend/: docs/ is beside it)
  const text = readFileSync(`../docs/${page.replace(/\/$/, '')}.md`, 'utf8')
  if (!anchor) return
  const headings = Array.from(text.replace(/```[\s\S]*?```/g, '').matchAll(/^#{2,6}\s+(.*?)\s*$/gm), match => slug(match[1]))
  expect(headings).toContain(anchor)
})

test('a hint with a place in the guide links to it in a new tab: the link is no part of the description, and its click is not cancelled', async () => {
  render(
    <label>
      <input type="checkbox" aria-describedby="more" /> A box{' '}
      <Hint id="more" doc={GUIDE.settingsAgents}>
        The rest of the note.
      </Hint>
    </label>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'About this' }))
  const link = screen.getByRole('link', { name: 'Learn more →' })
  expect(link).toHaveAttribute('href', '/guide/settings/#agents')
  expect(link).toHaveAttribute('target', '_blank')
  expect(screen.getByRole('checkbox')).toHaveAccessibleDescription('The rest of the note.')
  // (fireEvent says false where a handler cancelled the click: the box's would, in a label.)
  expect(fireEvent.click(link)).toBe(true)
  expect(screen.getByRole('checkbox')).not.toBeChecked()
})
