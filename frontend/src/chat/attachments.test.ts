import { expect, test } from 'vitest'
import type { Attachment } from '../api/types'
import { shown } from './attachments'

const file = (name: string, kind: Attachment['kind'], over: Partial<Attachment> = {}): Attachment => ({
  id: name,
  conversation_id: 'c1',
  message_id: null,
  frame_of: null,
  name,
  kind,
  mime: 'application/octet-stream',
  size: 4096,
  summary: '132 lines',
  given_to: [],
  shown_to: {},
  keep_in_project: false,
  created_at: '2026-10-25T10:00:00Z',
  ...over,
})

test('a file as its chip says it, by its kind', () => {
  expect(shown(file('App.TSX', 'text'))).toEqual({
    label: '.tsx',
    colour: '--file-code',
    meta: 'code · 4 KB · 132 lines',
  })
  expect(shown(file('notes.txt', 'text'))).toEqual({
    label: 'TXT',
    colour: '--file-code',
    meta: 'text · 4 KB · 132 lines',
  })
  expect(shown(file('LICENSE', 'text', { size: 12 }))).toEqual({
    label: 'TXT',
    colour: '--file-code',
    meta: 'text · 12 B · 132 lines',
  })
  expect(shown(file('a.png', 'image', { mime: 'image/png' }))).toEqual({
    label: 'PNG',
    colour: '--file-img',
    meta: 'image · 4 KB · seen by a model that sees images',
  })
  expect(shown(file('a.png', 'image', { mime: 'image/png' }), 0, null, 'not shown: why').meta).toBe(
    'image · 4 KB · not shown: why',
  )
  expect(
    shown(
      file('a.png', 'image', { mime: 'image/png', shown_to: { a: 'shown to x', b: 'not shown to y' } }),
      0,
      null,
      'not shown: why',
    ).meta,
  ).toBe('image · 4 KB · shown to x; not shown to y')
  expect(shown(file('a.pdf', 'pdf', { summary: '3 pages' }))).toEqual({
    label: 'PDF',
    colour: '--file-doc',
    meta: '3 pages',
  })
  expect(shown(file('a.docx', 'docx', { summary: '2 pages' }))).toEqual({
    label: 'DOC',
    colour: '--file-doc',
    meta: '2 pages',
  })
  expect(shown(file('clip.mp4', 'video'))).toEqual({
    label: 'MP4',
    colour: '--file-vid',
    meta: 'video · 4 KB · taking frames…',
  })
  expect(shown(file('clip', 'video'), 2)).toEqual({
    label: 'VID',
    colour: '--file-vid',
    meta: 'video · 4 KB · kept as a file, 2 frames taken',
  })
  expect(shown(file('clip.mov', 'video', { size: 30 * 2 ** 20 }), 2).meta).toBe(
    'video · 30.0 MB · not kept, 2 frames taken',
  )
  expect(shown(file('clip.mov', 'video'), 2, 'no frames: why').meta).toBe('video · 4 KB · no frames: why')
  expect(shown(file('clip.mov', 'video', { shown_to: { a: 'its frames shown to x' } }), 2, 'no frames: why').meta).toBe(
    'video · 4 KB · its frames shown to x',
  )
  expect(shown(file('run.exe', 'executable'))).toEqual({
    label: 'EXE',
    colour: '--file-other',
    meta: '4 KB · by name and size only: never read or run',
  })
  expect(shown(file('data.bin', 'file', { summary: 'not read' }))).toEqual({
    label: 'FILE',
    colour: '--file-other',
    meta: '4 KB · not read',
  })
})
