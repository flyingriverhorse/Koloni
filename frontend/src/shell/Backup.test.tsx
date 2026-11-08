import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { Backup, HELD_NOTE, RESTORED_NOTE, SECRETS_NOTE, TRUST_NOTE } from './Backup'

afterEach(() => vi.unstubAllGlobals())

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
const MADE = '2026-10-28T10:00:00+00:00'
const RESTORED = { made_at: MADE, secrets: false, need_keys: ['provider Anthropic', 'MCP server gh'] }

/** The server, by what is asked: `staged` is what GET /backup/staged answers. */
function server(staged: unknown = { staged: null, failed: null }, restore: () => Response = () => json(RESTORED)) {
  const asked = vi.fn(async (address: string, init?: RequestInit) => {
    if (address === '/api/backup/staged') return init?.method === 'DELETE' ? new Response(null, { status: 204 }) : json(staged)
    return restore()
  })
  vi.stubGlobal('fetch', asked)
  return asked
}

// (In Settings › The app since tek-ev: in sight, no button to open it.)
const open = async () => screen.getByRole('region', { name: 'Your data' })

test('Export everything is a POST to the export, saved with no key in its address, secrets left out unless the box is ticked; a refusal is said here', async () => {
  const zip = () => new Response('PK', { headers: { 'Content-Disposition': 'attachment; filename="koloni-2026-11-06.zip"' } })
  const asked = server(undefined, zip)
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:zip'), revokeObjectURL: vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  render(<Backup />)
  const panel = await open()
  const box = within(panel).getByRole('checkbox', { name: 'Include API keys and secrets (keep this file safe)' })
  expect(box).not.toBeChecked()
  expect(box).toHaveAccessibleDescription(SECRETS_NOTE)
  await userEvent.click(within(panel).getByRole('button', { name: 'Export everything' }))
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
  expect(asked).toHaveBeenLastCalledWith('/api/backup/export?secrets=false', expect.objectContaining({ method: 'POST' }))
  expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('koloni-2026-11-06.zip')
  await userEvent.click(box)
  await userEvent.click(within(panel).getByRole('button', { name: 'Export everything' }))
  await waitFor(() => expect(click).toHaveBeenCalledTimes(2))
  expect(asked).toHaveBeenLastCalledWith('/api/backup/export?secrets=true', expect.objectContaining({ method: 'POST' }))
  expect(panel).toHaveTextContent(TRUST_NOTE)
  // refused: said in the panel, nothing saved
  asked.mockResolvedValueOnce(json({ detail: 'origin not allowed' }, 403))
  await userEvent.click(within(panel).getByRole('button', { name: 'Export everything' }))
  expect(await within(panel).findByRole('alert')).toHaveTextContent('origin not allowed')
  expect(click).toHaveBeenCalledTimes(2)
  click.mockRestore()
})

test('Restore from a file sends the .zip and says when it is restored, that everything waits for Resume, and which keys are to be given again', async () => {
  const asked = server()
  render(<Backup />)
  const panel = await open()
  const file = new File(['zip'], 'koloni-2026-10-28.zip', { type: 'application/zip' })
  await userEvent.upload(within(panel).getByLabelText('An export to restore'), file)
  expect(asked).toHaveBeenCalledWith('/api/backup/restore', expect.objectContaining({ method: 'POST', body: file }))
  const said = await within(panel).findByRole('status')
  expect(said).toHaveTextContent(`A restore of ${new Date(MADE).toLocaleString()} waits for the next start.`)
  expect(said).toHaveTextContent(RESTORED_NOTE)
  expect(said).toHaveTextContent(HELD_NOTE)
  expect(said).toHaveTextContent('The file has no keys. These need theirs again: provider Anthropic, MCP server gh.')
})

test('a staged restore is shown when the panel opens, and Cancel gives it up; a failed one says where it is kept', async () => {
  const asked = server({ staged: RESTORED, failed: 'C:\\koloni\\runtime\\restore.failed-20261028T100000000000' })
  render(<Backup />)
  const panel = await open()
  expect(await within(panel).findByRole('status')).toHaveTextContent('waits for the next start')
  expect(panel).toHaveTextContent('A restore could not be applied at the last start: it is kept in C:\\koloni\\runtime\\restore.failed-20261028T100000000000')
  await userEvent.click(within(panel).getByRole('button', { name: 'Cancel' }))
  expect(asked).toHaveBeenCalledWith('/api/backup/staged', expect.objectContaining({ method: 'DELETE' }))
  expect(within(panel).queryByRole('status')).not.toBeInTheDocument()
})

test('a refused restore says why, and no note of a restore', async () => {
  server(undefined, () => json({ detail: 'not restored: it is not a KOLONİ export: it has no manifest.json' }, 422))
  render(<Backup />)
  const panel = await open()
  await userEvent.upload(within(panel).getByLabelText('An export to restore'), new File(['x'], 'other.zip', { type: 'application/zip' }))
  expect(await within(panel).findByRole('alert')).toHaveTextContent('not restored: it is not a KOLONİ export: it has no manifest.json')
  expect(within(panel).queryByRole('status')).not.toBeInTheDocument()
})
