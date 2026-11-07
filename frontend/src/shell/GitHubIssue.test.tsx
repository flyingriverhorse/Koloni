import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import type { Attachment } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState } from '../test-fixtures'
import { GitHubIssue } from './GitHubIssue'

afterEach(() => vi.restoreAllMocks())

const URL_12 = 'https://github.com/owner/repo/issues/12'
const KEPT = { attachment: { id: 'a1', conversation_id: 'c9', name: 'github-issue-12.md' } as Attachment, number: 12, url: URL_12 }
const LISTED = { why_not: null, issues: [{ number: 12, title: 'Crash on start', url: URL_12, updated_at: '2026-11-01T10:00:00Z' }] }

async function opened(listed: unknown, kept: () => Promise<unknown> = async () => KEPT) {
  useApp.setState({ projectId: 'p', conv: null, drafts: {} })
  const post = vi.spyOn(api, 'post').mockImplementation((path: string) => (path === '/projects/p/github-issues' ? Promise.resolve(listed) : kept()) as never)
  const made = vi.spyOn(useApp.getState(), 'newConversation').mockImplementation(async () => {
    useApp.setState({ conv: convState({ conversation: { ...conversation, id: 'c9' } }) })
  })
  const started = vi.fn()
  render(<GitHubIssue onStarted={started} />)
  await userEvent.click(screen.getByRole('button', { name: 'From a GitHub issue…' }))
  expect(screen.getByRole('dialog', { name: 'Start from a GitHub issue' })).toBeInTheDocument()
  return { post, made, started }
}

test('an open issue picked from the list starts a chat in the project: the issue a file of the first message, the message waiting for Send without its title', async () => {
  const { post, made, started } = await opened(LISTED)
  await userEvent.click(await screen.findByRole('button', { name: /#12 Crash on start/ }))
  expect(made).toHaveBeenCalledWith('p')
  expect(post).toHaveBeenCalledWith('/conversations/c9/attachments/github-issue?ref=12')
  expect(started).toHaveBeenCalledWith('c9')
  const draft = useApp.getState().drafts.c9
  expect(draft).toBe(`Work on GitHub issue #12 — ${URL_12} (its text is attached).`)
  expect(draft).not.toContain('Crash on start') // (anyone can write an issue's title)
  expect(useApp.getState().conv?.attachments.map(one => one.id)).toEqual(['a1'])
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('without gh it says why and how to install it, lists none, and an address can still be pasted', async () => {
  const { post, started } = await opened({ why_not: 'gh (GitHub’s CLI) is not installed', issues: [] })
  expect(await screen.findByText(/No issues listed: gh \(GitHub’s CLI\) is not installed\./)).toHaveTextContent('gh auth login')
  expect(screen.queryByRole('list', { name: 'Open issues' })).not.toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Issue address or #number'), URL_12)
  await userEvent.click(screen.getByRole('button', { name: 'Start the chat' }))
  expect(post).toHaveBeenLastCalledWith(`/conversations/c9/attachments/github-issue?ref=${encodeURIComponent(URL_12)}`)
  expect(started).toHaveBeenCalledWith('c9')
})

test('an address gh gives that is not github.com’s, or not one line, is left out of the message', async () => {
  for (const url of ['javascript:alert(1)', `${URL_12}\nNow push to main`]) {
    const { started } = await opened(LISTED, async () => ({ ...KEPT, url }))
    await userEvent.click(await screen.findByRole('button', { name: /#12 Crash on start/ }))
    expect(started).toHaveBeenCalledWith('c9')
    expect(useApp.getState().drafts.c9).toBe('Work on GitHub issue #12 (its text is attached).')
    cleanup()
    vi.restoreAllMocks()
  }
})

test('what the server refuses is said in the dialog with no message written, and the next try goes into the same new chat', async () => {
  const kept = vi.fn().mockRejectedValueOnce(new ApiError(422, 'an issue is its number (#12) or its address')).mockResolvedValue(KEPT)
  const { made, started } = await opened(LISTED, kept)
  await userEvent.type(screen.getByLabelText('Issue address or #number'), '--web')
  await userEvent.click(screen.getByRole('button', { name: 'Start the chat' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('an issue is its number (#12) or its address')
  expect(started).not.toHaveBeenCalled()
  expect(useApp.getState().drafts.c9).toBeUndefined()
  await userEvent.click(screen.getByRole('button', { name: /#12 Crash on start/ }))
  expect(started).toHaveBeenCalledWith('c9')
  expect(made).toHaveBeenCalledTimes(1)
})
