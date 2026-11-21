import { expect, type Page, test } from './fixtures'
import { openFreshConversation, say } from './helpers'

// The chat, round 2 (0.1.5): VS Code's sizes, a turn without a frame, its steps folded at its end. No model plays a turn
// of many steps with a sub-agent: one real turn gives a real record, and the page is handed it with those steps in it.

type Json = Record<string, unknown>
type Snap = Json & { agents: Json[]; messages: Json[]; runs: Json[] }

/** A real turn's record, its lead and its answer. */
async function realTurn(page: Page) {
  const id = await openFreshConversation(page)
  await say(page, 'hello, a turn of steps', 'Hello! Ask me to read or change a file.')
  const snap = (await (await page.request.get(`/api/conversations/${id}`)).json()) as Snap
  return { id, snap, lead: snap.agents[0], answer: snap.messages.find(m => m.role === 'assistant')! }
}

/** The page shown `record` in place of the chat's own. */
async function shown(page: Page, id: string, record: Json) {
  await page.route(`**/api/conversations/${id}`, route => (route.request().method() === 'GET' ? route.fulfill({ json: record }) : route.fallback()))
  await page.reload()
}

test('a finished turn folds its steps into one line that counts what failed; a sub-agent stays outside', async ({ page }) => {
  const { id, snap, lead, answer } = await realTurn(page)
  const at = String(answer.created_at)
  const call = (cid: string, message: string, seq: number, name: string, args: Json, status = 'succeeded') => ({
    id: cid, run_id: answer.run_id, agent_id: lead.id, message_id: message, origin: 'koloni', parent_call_id: null, outside_folder: null, why_asked: null,
    seq, provider_call_id: cid, name, arguments: JSON.stringify(args), status, result: 'ok', started_at: at, ended_at: at,
  })
  const step = (mid: string, content: string) => ({ ...answer, id: mid, content })
  const record = {
    ...snap,
    // (A fake turn is over in under a second: this one took 32s.)
    runs: snap.runs.map(r => ({ ...r, ended_at: new Date(Date.parse(String(r.started_at)) + 32_000).toISOString() })),
    agents: [lead, { ...lead, id: 'k2-coder', name: 'Coder', role_name: 'Coder', parent_agent_id: lead.id, depth: 1, status: 'completed', task: 'Fix the greeting', tool_call_id: 'k2-c3' }],
    messages: [snap.messages.find(m => m.role === 'user'), step('k2-m1', 'I’ll read it first.'), step('k2-m2', 'The Coder fixed it; I’ll check its edit.'), answer],
    tool_calls: [
      call('k2-c1', 'k2-m1', 101, 'read_file', { path: 'a.py' }),
      call('k2-c2', 'k2-m1', 102, 'read_file', { path: 'gone.py' }, 'failed'),
      call('k2-c3', 'k2-m1', 103, 'spawn_agent', { role: 'Coder', task: 'Fix the greeting' }),
      call('k2-c4', 'k2-m2', 104, 'read_file', { path: 'a.py' }),
    ],
  }
  await shown(page, id, record)
  const chat = page.getByRole('region', { name: 'Chat' })
  const fold = chat.locator('details.turn-steps')
  await expect(fold.locator('summary')).toHaveText(/^Completed 4 steps in \d+s/)
  await expect(fold.locator('summary .tag-del')).toHaveText('1 failed')
  await expect(chat.getByText('I’ll read it first.')).toBeHidden()
  // The sub-agent's row stands outside, in sight; the answer under it.
  await expect(chat.getByRole('button', { name: /^Coder Fix the greeting/ })).toBeVisible()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  await fold.locator('summary').click()
  await expect(chat.getByText('I’ll read it first.')).toBeVisible()
})

test('while a command runs the status line over the box and the Orchestrator’s box say what it does and for how long; Stop there ends the turn', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Permission level').selectOption('full_auto')
  await page.getByLabel('Message').fill('run slow.py')
  await page.getByRole('button', { name: 'Send' }).click()
  const status = chat.locator('.composer-status')
  await expect(status).toContainText(/python -u slow\.py · \d+s/, { timeout: 15_000 })
  await expect(page.locator('.react-flow__node-agent .node-now')).toContainText(/python -u slow\.py · \d+s/)
  // Its clock ticks every second: no live region reads it out.
  expect(await status.evaluate(el => el.closest('[aria-live],[role=status],[role=alert]') === null && !el.querySelector('[aria-live],[role=status]'))).toBe(true)
  await status.getByRole('button', { name: 'Stop' }).click()
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(status).toHaveText(/^Orchestrator is ready/)
})
