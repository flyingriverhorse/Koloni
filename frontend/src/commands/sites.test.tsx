import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { AllowedWeb } from '../api/types'
import { AllowList } from './AllowList'
import { ProjectSites } from './Sites'

const site = (id: string, host: string, ask_first = false): AllowedWeb => ({ id, conversation_id: null, project_id: 'p', kind: 'page', host, ask_first, created_at: 't' })

test('K-tarayici-disari A3: a site is added by hand in the chat’s rules, marked Ask first or not; a refused one says why', async () => {
  const onAllowSite = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce({ detail: 'https://printer: printer is on this machine or its network' })
  render(<AllowList rules={[]} web={[]} onRemove={vi.fn()} onAllowHost={vi.fn()} onAllowSite={onAllowSite} />)
  await userEvent.click(screen.getByRole('button', { name: '0 rules' }))
  const host = screen.getByLabelText('Allow a site')
  expect(screen.getByRole('button', { name: 'Allow site' })).toBeDisabled()
  await userEvent.type(host, ' docs.test ')
  await userEvent.click(screen.getByRole('checkbox', { name: 'Ask first for the new site' }))
  await userEvent.click(screen.getByRole('button', { name: 'Allow site' }))
  expect(onAllowSite).toHaveBeenCalledWith('docs.test', true)
  expect(host).toHaveValue('')
  expect(screen.getByRole('checkbox', { name: 'Ask first for the new site' })).not.toBeChecked()
  await userEvent.type(host, 'printer{Enter}')
  expect(onAllowSite).toHaveBeenLastCalledWith('printer', false)
  expect(await screen.findByRole('alert')).toHaveTextContent('printer is on this machine or its network')
  expect(host).toHaveValue('printer')
})

test('Project settings lists the project’s sites: each marked, removed, or one added, and read again after each', async () => {
  let listed = [site('w1', 'docs.test'), site('w2', 'shop.test', true)]
  const get = vi.spyOn(api, 'get').mockImplementation(async () => listed as never)
  const patch = vi.spyOn(api, 'patch').mockResolvedValue({} as never)
  const remove = vi.spyOn(api, 'delete').mockImplementation(async () => {
    listed = listed.slice(1)
  })
  const post = vi.spyOn(api, 'post').mockResolvedValue({} as never)
  render(<ProjectSites projectId="p" />)
  expect(await screen.findByText('docs.test')).toBeInTheDocument()
  expect(get).toHaveBeenCalledWith('/projects/p/sites')
  expect(screen.getByRole('checkbox', { name: 'Ask first for shop.test' })).toBeChecked()
  await userEvent.click(screen.getByRole('checkbox', { name: 'Ask first for docs.test' }))
  expect(patch).toHaveBeenCalledWith('/allowed-web/w1', { ask_first: true })
  await userEvent.click(screen.getByRole('button', { name: 'Remove site docs.test' }))
  expect(remove).toHaveBeenCalledWith('/allowed-web/w1')
  await waitFor(() => expect(screen.queryByText('docs.test')).not.toBeInTheDocument())
  await userEvent.type(screen.getByLabelText('Allow a site'), 'new.test{Enter}')
  expect(post).toHaveBeenCalledWith('/projects/p/sites', { host: 'new.test', ask_first: false })
  expect(get).toHaveBeenCalledTimes(4)
})
