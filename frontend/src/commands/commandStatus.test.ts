import { expect, test } from 'vitest'
import type { Command } from '../api/types'
import { commandStatus } from './commandStatus'

type Stated = Parameters<typeof commandStatus>[0]
const of = (status: Command['status'], over: Partial<Stated> = {}) => {
  const { label, tone } = commandStatus({ status, exit_code: null, started_at: '2026-10-05T10:00:00Z', ...over })
  return `${label} / ${tone}`
}

test('how a command’s state reads, for every state', () => {
  expect(of('proposed')).toBe('waits for you / warn')
  expect(of('approved')).toBe('approved — not started yet / muted')
  expect(of('running')).toBe('working / accent')
  expect(of('exited')).toBe('ended · exit code not reported / muted')
  expect(of('exited', { exit_code: 0 })).toBe('exit 0 / ok')
  expect(of('exited', { exit_code: 2 })).toBe('exit 2 / del')
  expect(of('timed_out')).toBe('timed out / del')
  expect(of('killed')).toBe('killed / muted')
  expect(of('rejected')).toBe('rejected / muted')
  expect(of('failed_to_start')).toBe('did not start / del')
  expect(of('blocked')).toBe('blocked: its read-only sandbox refused a write / del')
  expect(of('interrupted')).toBe('interrupted / warn')
  expect(of('interrupted', { started_at: null })).toBe('approved — the work ended before it ran / muted')
})

test('a server’s, kept running: its own words where it has them, else a command’s', () => {
  const server = (status: Command['status'], over: Partial<Stated> = {}) => of(status, { keep_running: true, ...over })
  expect(server('running')).toBe('starting… / accent')
  expect(server('running', { preview_url: 'http://127.0.0.1:5173' })).toBe('running / accent')
  expect(server('killed')).toBe('stopped / muted')
  expect(server('exited', { exit_code: 0 })).toBe('exited 0 / muted')
  expect(server('exited', { exit_code: 1 })).toBe('exited 1 / del')
  expect(server('exited')).toBe('ended · exit code not reported / muted')
  expect(server('interrupted')).toBe('stopped when KOLONİ closed / muted')
  expect(server('interrupted', { started_at: null })).toBe('approved — the work ended before it ran / muted')
  expect(server('proposed')).toBe('waits for you / warn')
  expect(server('timed_out')).toBe('timed out / del')
  // (Not kept running: a preview's address changes nothing.)
  expect(of('running', { keep_running: false, preview_url: 'http://127.0.0.1:5173' })).toBe('working / accent')
})
