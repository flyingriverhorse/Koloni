import os from 'node:os'
import path from 'node:path'
import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, say, settled } from './helpers'

// 89k: a chat on Claude Code that has had a turn, given another Claude Code model in its picker, is told the next turn costs more.
// Nothing runs on Claude Code: its turn ran on the fake model, then the chat was moved, and no message follows.
const CLI = 'Claude 89k'
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'mk-shots')
const SWITCH = 'Another model has no cache of this chat yet: its next turn writes everything it is sent to the cache again, so it costs more.'

async function clean(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (provider.name === CLI) expect((await request.delete(`/api/providers/${provider.id}`, { headers: OWN })).ok()).toBe(true)
}

test.beforeEach(async ({ request }) => clean(request))
test.afterEach(async ({ request }) => clean(request))

for (const theme of ['light', 'dark'] as const) {
  test(`another Claude Code model for a chat with a turn says what it costs (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const made = await request.post('/api/providers', { headers: OWN, data: { name: CLI, kind: 'claude_cli', executable: 'no-such-claude-for-89k' } })
    expect(made.ok()).toBe(true)
    const id = (await made.json()).id as string
    const cid = await openFreshConversation(page)
    await say(page, 'hello 89k', 'Hello! Ask me to read or change a file.')
    // The chat moves onto Claude Code after its turn; no message follows, so nothing runs there.
    expect((await request.patch(`/api/conversations/${cid}`, { headers: OWN, data: { provider_id: id, model_id: null } })).ok()).toBe(true)
    const picker = page.getByRole('button', { name: /^Model: / })
    await expect(picker).toHaveAccessibleName(new RegExp(CLI))
    await picker.click()
    await page.getByLabel('Model name').fill('claude-sonnet-5-5')
    const panel = page.getByRole('form', { name: 'Model for this conversation' })
    await expect(panel.getByText(SWITCH)).toBeVisible()
    await settled(page)
    await panel.screenshot({ path: path.join(SHOTS, `89k-switch-${theme}.png`) })
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}
