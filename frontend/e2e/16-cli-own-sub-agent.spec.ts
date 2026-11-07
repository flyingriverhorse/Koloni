import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, openFreshConversation, openAgentFold } from './helpers'
import { FAKE_CLAUDE } from './paths.mjs'

/** The stand-in provider is taken off the list, however many of it there are. */
async function removeClaudeCode(request: APIRequestContext) {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === 'Claude Code')) {
    await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  }
}

// The backend is started with a stand-in for Claude Code working natively
// (start-backend.mjs): it hands a look-around to a sub-agent of its own.
test.describe('with Claude Code working natively as a provider', () => {
  // The provider is added before the test and removed after it in hooks: the list is put
  // back for the specs that follow also when the test fails half-way or times out.
  test.beforeEach(async ({ page, request }) => {
    await removeClaudeCode(request)
    // At Full auto: since slice 89b every tool of Claude Code's is asked of KOLONİ first, and
    // at the level a new conversation has, its Agent and Bash would each wait on a card.
    const id = await openFreshConversation(page)
    const patched = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })
    expect(patched.ok()).toBe(true)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill('Claude Code')
    await page.getByLabel('Kind').selectOption({ label: 'Claude Code (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_CLAUDE)
    await page.getByLabel('How it runs').selectOption('native')
    await page.getByRole('button', { name: 'Add provider' }).click()
    await expect(page.getByRole('button', { name: /^Claude Code/ })).toBeVisible()
  })

  test.afterEach(async ({ request }) => {
    await removeClaudeCode(request)
  })

  test('a sub-agent of Claude Code’s own is a box inside its agent’s box, and a block in its window', async ({ page }) => {
    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Model: Local/ }).click()
    await chat.getByLabel('Provider').selectOption({ label: 'Claude Code' })
    await chat.getByRole('button', { name: 'Use this model' }).click()
    await expect(chat.getByRole('button', { name: /^Model: Claude Code/ })).toBeVisible()
    await page.getByLabel('Message').fill('what does hello.py print?')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('The helper says it prints hi.')).toBeVisible()

    // One agent of KOLONİ's. Its own sub-agent is not a second one: it is counted on the agent's node (the user's,
    // 5 Nov) - what it did is in the agent's window.
    const lead = page.locator('.react-flow__node-agent')
    await expect(lead).toHaveCount(1)
    await expect(lead).toContainText('1 own sub-agent')
    await expect(page.locator('.react-flow__node-subagent')).toHaveCount(0)

    // An agent that works with its own tools has its window open. There the sub-agent is
    // one block among its steps, with its task, its work and its report.
    const steps = await openAgentFold(page.getByRole('region', { name: 'Agent window' }), 'Every step as recorded')
    const block = steps.getByRole('group', { name: 'Own sub-agent: Look around' })
    await expect(block).toContainText('done')
    await block.getByRole('button', { name: /Look around/ }).click()
    await expect(block.getByText('Read hello.py and say what it prints')).toBeVisible()
    await expect(block.getByText('Its report')).toBeVisible()
    await expect(block.getByText('It prints hi.')).toBeVisible()

    // It is drawn from what is on record: the same after a reload.
    await page.reload()
    await expect(lead).toContainText('1 own sub-agent')
  })
})

test('the stand-in provider does not outlive its test', async ({ request }) => {
  const listed: { name: string }[] = await (await request.get('/api/providers')).json()
  expect(listed.map(p => p.name)).not.toContain('Claude Code')
})
