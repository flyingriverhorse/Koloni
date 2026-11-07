import { readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, openFreshConversation, openAgentFold } from './helpers'
import { E2E_ROOT, FAKE_AGY, PROJECT_DIR } from './paths.mjs'

/** The stand-in provider is taken off the list, however many of it there are. */
async function removeAgy(request: APIRequestContext) {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === 'agy')) {
    await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  }
}

// The backend is started with a stand-in for the agy CLI (start-backend.mjs): it looks at
// a file with a tool of its own, asks for a command it then refuses itself, and answers.
test.describe('with the agy CLI as a provider that only reads', () => {
  test.beforeEach(async ({ page, request }) => {
    await removeAgy(request)
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill('agy')
    await page.getByLabel('Kind').selectOption({ label: 'agy (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_AGY)
    // Reading is how it runs unless native is chosen, and the page says what that means.
    await expect(page.getByLabel('How it runs')).toHaveValue('reads')
    await expect(page.getByRole('note')).toContainText('agy itself refuses to write a file or run a command')
    await page.getByRole('button', { name: 'Add provider' }).click()
    await expect(page.getByRole('button', { name: /^agy/ })).toBeVisible()
  })

  test.afterEach(async ({ request }) => {
    await removeAgy(request)
  })

  test('a turn at the ask level: what it read is its own tool, and what it was refused is not done', async ({ page }) => {
    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Model: Local/ }).click()
    await chat.getByLabel('Provider').selectOption({ label: 'agy' })
    await chat.getByRole('button', { name: 'Use this model' }).click()
    await expect(chat.getByRole('button', { name: /^Model: agy/ })).toBeVisible()
    // Nothing says it needs Full auto: it runs at the level a new conversation has.
    await expect(chat.getByText(/only runs when the level is Full auto/)).toHaveCount(0)
    await page.getByLabel('Message').fill('what does hello.py print?')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('It prints hi. I could not run it here.')).toBeVisible()

    // On the canvas: one agent, on the model the CLI said it ran on; its own tools counted, and no command, since none
    // ran (that it only reads is in its window - the user's, 5 Nov: the node is three lines).
    const lead = page.locator('.react-flow__node-agent')
    await expect(lead).toHaveCount(1)
    await expect(lead).toContainText('agy · gemini-stand-in')
    await expect(lead.locator('.node-body > *').last()).toHaveText('2 tools')

    // Its window is open: it says that it only reads (why, under Details), and shows the refused step as refused.
    const window = page.getByRole('region', { name: 'Agent window' })
    await expect(window.getByText('reads only', { exact: true })).toBeVisible()
    await expect((await openAgentFold(window, 'Details')).getByRole('note')).toContainText('Reads only: on this provider it works with the CLI’s own tools')
    const steps = await openAgentFold(window, 'Every step as recorded')
    await expect(steps.getByRole('button', { name: /agy__view_file.*own tool.*done/ })).toBeVisible()
    const refused = steps.getByRole('button', { name: /agy__run_command.*own tool.*rejected/ })
    await refused.click()
    await expect(
      window.getByText(/refused by the CLI: permission check failed for command "python hello.py": user denied permission/),
    ).toBeVisible()

    // How it was started: through the command the page was given, in the project, without
    // the flag that lets it change things, the prompt on stdin and not on the command line.
    const seen = JSON.parse(readFileSync(path.join(E2E_ROOT, 'agy-record.json'), 'utf8'))
    expect(seen.argv).toEqual(['--input-format', 'stream-json', '--output-format', 'stream-json', '-p='])
    expect(path.resolve(seen.cwd)).toBe(path.resolve(PROJECT_DIR))
    expect(JSON.parse(seen.stdin).message.content).toContain('what does hello.py print?')

    // It is drawn from what is on record: the same after a reload.
    await page.reload()
    await expect(lead.locator('.node-body > *').last()).toHaveText('2 tools')
  })
})

test('the agy stand-in does not outlive its test', async ({ request }) => {
  const listed: { name: string }[] = await (await request.get('/api/providers')).json()
  expect(listed.map(p => p.name)).not.toContain('agy')
})
