import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { openEvents } from './sse'

/**
 * Behaves like the browser's EventSource in the one way that matters here: an
 * event without an `id:` line reports the id of the last event that had one.
 */
class StickyEventSource {
  static last: StickyEventSource
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  private lastId = ''
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null

  url: string

  constructor(url: string) {
    this.url = url
    StickyEventSource.last = this
  }
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener)
  }
  close() {}
  /** Deliver a frame; `id` is what the server put on the wire (undefined: no id line). */
  frame(type: string, data: unknown, id?: number) {
    if (id !== undefined) this.lastId = String(id)
    this.listeners.get(type)?.({ data: JSON.stringify(data), lastEventId: this.lastId } as MessageEvent<string>)
  }
}

beforeEach(() => vi.stubGlobal('EventSource', StickyEventSource))
afterEach(() => vi.unstubAllGlobals())

test('events sent without an id are reported as transient, whatever came before', () => {
  const seen: [number | null, string][] = []
  openEvents('c', 0, (id, type) => seen.push([id, type]), () => {}, () => {})
  const source = StickyEventSource.last

  source.frame('message.created', {}, 5)
  source.frame('message.delta', { text: 'Hel' })
  source.frame('run.thinking', {})
  source.frame('command.output', { text: 'out' })
  source.frame('message.sync', {})
  source.frame('command.sync', {})
  source.frame('message.completed', {}, 6)

  expect(seen).toEqual([
    [5, 'message.created'],
    [null, 'message.delta'],
    [null, 'run.thinking'],
    [null, 'command.output'],
    [null, 'message.sync'],
    [null, 'command.sync'],
    [6, 'message.completed'],
  ])
})

test('a change to the project’s memory is heard, from this conversation or from another', () => {
  const seen: [number | null, string][] = []
  openEvents('c', 0, (id, type) => seen.push([id, type]), () => {}, () => {})
  const source = StickyEventSource.last
  source.frame('memory.changed', { project_id: 'p' }, 7) // written in this conversation: on record
  source.frame('memory.changed', { project_id: 'p' }) // from elsewhere: passed on, with no id of its own
  expect(seen.map(([, type]) => type)).toEqual(['memory.changed', 'memory.changed'])
  expect(seen[0][0]).toBe(7)
})

test('a topic that is made or named is heard', () => {
  const seen: [number | null, string][] = []
  openEvents('c', 0, (id, type) => seen.push([id, type]), () => {}, () => {})
  const source = StickyEventSource.last
  source.frame('topic.created', { id: 't1' }, 8)
  source.frame('topic.updated', { id: 't1' }, 9)
  expect(seen).toEqual([[8, 'topic.created'], [9, 'topic.updated']])
})
