import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type APIRequestContext, type Page, test } from './fixtures'
import { OWN, contrasts, openAgentFold, openFreshConversation, settled, shot } from './helpers'
import { E2E_ROOT, PYTHON, REPO_ROOT } from './paths.mjs'

// 89j: while Claude Code works natively, its node says how full its context is by its own count (`get_context_usage`,
// answered by the stand-in CLI); once it has finished, nothing more is said of it. A stand-in of its own, with its own plan:
// the shared one (start-backend.mjs) is left as it is.
const NAME = 'Live Claude'
const plan = path.join(E2E_ROOT, 'live-claude-plan.json')
const command = path.join(E2E_ROOT, process.platform === 'win32' ? 'live-claude.cmd' : 'live-claude')
const fake = path.join(REPO_ROOT, 'tests', 'fake_claude_native_cli.py')
const lowContrast = async (page: Page, selector: string) => (await page.locator(selector).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

async function removeIt(request: APIRequestContext) {
  for (const provider of (await (await request.get('/api/providers')).json()) as { id: string; name: string }[])
    if (provider.name === NAME) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.afterEach(async ({ request }) => {
  await removeIt(request)
})

for (const theme of ['light', 'dark'] as const) {
  test(`a CLI agent's node says how full its context is while it works, and nothing once it has finished (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    writeFileSync(
      plan,
      JSON.stringify({
        record: path.join(E2E_ROOT, 'live-claude-record.json'),
        context: { totalTokens: 34000, maxTokens: 200000, rawMaxTokens: 200000, percentage: 17 },
        script: [{ say: 'Looking at hello.py.' }, { sleep: 8 }, { say: 'It prints hi.' }],
      }),
    )
    if (process.platform === 'win32') writeFileSync(command, `@set "FAKE_CLI_PLAN=${plan}"\r\n@"${PYTHON}" "${fake}" %*\r\n`)
    else writeFileSync(command, `#!/bin/sh\nFAKE_CLI_PLAN="${plan}" exec "${PYTHON}" "${fake}" "$@"\n`, { mode: 0o755 })
    await removeIt(request)
    const made = await request.post('/api/providers', { headers: OWN, data: { name: NAME, kind: 'claude_cli', executable: command, mode: 'native' } })
    expect(made.ok()).toBe(true)
    const provider = (await made.json()) as { id: string }

    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page)
    const set = await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'full_auto', provider_id: provider.id } })
    expect(set.ok()).toBe(true)
    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    await page.getByLabel('Message').fill(`what does hello.py print? (${theme})`)
    await page.getByRole('button', { name: 'Send' }).click()

    const node = page.locator('.react-flow__node-agent')
    // (How full its context is, its window says under Details: its node is three lines - the user's, 5 Nov.)
    await openAgentFold(page.getByRole('region', { name: 'Agent window' }), 'Details')
    await expect(page.getByRole('region', { name: 'Agent window' }).getByText('17% full')).toBeVisible({ timeout: 15_000 })
    await node.click()
    // (Its window opened as it started: the inspector does not show it a second time, R160.)
    await expect(page.getByRole('complementary', { name: 'Inspector' }).getByText('Shown in its window.')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Agent window' }).getByText('17% full')).toBeVisible()
    await settled(page)
    await shot(page, `89j-live-node-${theme}`)
    expect(await lowContrast(page, '.react-flow__node-agent')).toEqual([])

    await expect(page.getByRole('region', { name: 'Chat' }).getByText('It prints hi.')).toBeVisible({ timeout: 20_000 })
    await expect(node).not.toContainText('context')
  })
}
