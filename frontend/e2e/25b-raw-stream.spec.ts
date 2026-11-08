import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, agentFold, openAgentFold, openFreshConversation, shot } from './helpers'
import { FAKE_AGY } from './paths.mjs'

/** The stand-in provider is taken off the list, however many of it there are. */
async function removeAgy(request: APIRequestContext) {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === 'agy')) {
    await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  }
}

// The backend is started with a stand-in for the agy CLI (start-backend.mjs): it looks at a
// file with a tool of its own, asks for a command it then refuses itself, and answers.
test.describe('with a CLI as a provider (the agy stand-in)', () => {
  // Added before the test and removed after it in hooks: the list is put back for the specs
  // that follow also when the test fails half-way.
  test.beforeEach(async ({ page, request }) => {
    await removeAgy(request)
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill('agy')
    await page.getByLabel('Kind').selectOption({ label: 'agy (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_AGY)
    await page.getByRole('button', { name: 'Add provider' }).click()
    await expect(page.getByRole('button', { name: /^agy/ })).toBeVisible()
  })

  test.afterEach(async ({ request }) => {
    await removeAgy(request)
  })

  test('the agent’s window shows its record, or what its CLI wrote itself', async ({ page }) => {
    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Model: Local/ }).click()
    await chat.getByLabel('Provider').selectOption({ label: 'agy' })
    await chat.getByRole('button', { name: 'Use this model' }).click()
    await expect(chat.getByRole('button', { name: /^Model: agy/ })).toBeVisible()
    await page.getByLabel('Message').fill('what does hello.py print?')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('It prints hi. I could not run it here.')).toBeVisible()

    // Its window is open on its record, Details folded; its raw steps say what it did, each tool with its result's size.
    const window = page.getByRole('region', { name: 'Agent window' })
    await expect(agentFold(window, 'Details')).not.toHaveAttribute('open')
    const steps = await openAgentFold(window, 'Every step as recorded')
    await expect(steps.getByRole('button', { name: /agy__view_file.*own tool.*done/ })).toBeVisible()
    await expect(steps.getByText(/^result [\d,]+ chars/).first()).toBeVisible()

    // Its raw stream is reached from the side panel, not its node (the user's, 5 Nov): the node picked, the panel's "Open
    // window", Details - what its CLI wrote itself is a click on Copy raw away, never drawn - neither its init blob nor whole
    // files it read (K-inspector).
    await window.getByRole('button', { name: 'Close agent window' }).click()
    await expect(window).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Raw stream of/ })).toHaveCount(0)
    await page.locator('.react-flow__node-agent .node-title').click()
    await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
    await openAgentFold(window, 'Details')
    await expect(agentFold(window, 'Details')).toHaveAttribute('open', '')
    await expect(window.getByRole('region', { name: 'Raw stream' })).toHaveCount(0)
    await expect(window.getByText(/"event": "init"/)).toHaveCount(0)
    // What it is, and what it is not.
    await expect(window.getByText(/Kept in memory only: it is gone when KOLONİ restarts\./)).toBeVisible()
    await expect(window.getByText(/Secrets KOLONİ knows \(of 8 characters or more\) are hidden/)).toBeVisible()
    await expect(window).not.toContainText(/terminal/i)
    await shot(page, '25b-raw-stream')

    // Copied, the CLI's own lines as it wrote them, from its first event to its last - with a step the record
    // passes over (the prompt it was handed).
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await window.getByRole('button', { name: 'Copy raw' }).click()
    await expect(window.getByRole('status').filter({ hasText: /^Copied \d+ lines$/ })).toBeVisible()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toMatch(/^\{"event": "init"/)
    expect(copied).toContain('"step_type": "user_input"')
    expect(copied).toContain('"tool_name": "view_file"')
    expect(copied).toMatch(/\{"event": "result".*$/)
  })
})
