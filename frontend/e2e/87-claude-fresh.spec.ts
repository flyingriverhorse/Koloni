import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'
import { APP_PORT, APP_URL } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 87: Claude Code's reading kept fresh. No claude is ever run here: the status line's reading is posted as
// KOLONİ's script posts it (from Node, with no Origin); Read now is answered in the page, on a provider whose
// command does not exist; and the default command's own checks (--help, auth status) are answered in the page too.
const CLI = 'Claude Code 87'
const ELSEWHERE = 'Claude Code 87 elsewhere'

// Deleting the last provider on the default command's account also forgets what was read of it: the reading
// posted here is not left for whatever runs after.
async function clean(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if ([CLI, ELSEWHERE].includes(provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => clean(request))
test.afterEach(async ({ request }) => clean(request))

for (const theme of ['light', 'dark'] as const) {
  test(`your own Claude Code session keeps the card fresh, Read now reads it in a short run, and the window says what to add (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const made = await request.post('/api/providers', { headers: OWN, data: { name: CLI, kind: 'claude_cli' } })
    expect(made.ok()).toBe(true)
    const id = (await made.json()).id as string
    // Nothing is left of an earlier run's reading.
    expect((await (await request.get(`/api/providers/${id}/limits`)).json()).unknown).toBeTruthy()
    const other = await request.post('/api/providers', { headers: OWN, data: { name: ELSEWHERE, kind: 'claude_cli', executable: 'no-such-claude-for-87' } })
    expect(other.ok()).toBe(true)
    const otherId = (await other.json()).id as string
    // The default command is the real claude: what the window would ask it is answered here.
    // So is the other's, whose command does not exist: a CLI not installed has no Read now.
    await page.route(
      url => [id, otherId].some(one => url.pathname === `/api/providers/${one}/availability`),
      route => route.fulfill({ json: { installed: true, signed_in: true, models: [] } }),
    )
    let read = 0
    await page.route(
      url => url.pathname === `/api/providers/${otherId}/limits/check`,
      route => {
        read += 1
        return route.fulfill({
          json: {
            unknown: null,
            read_at: new Date().toISOString(),
            source: 'a short run to read it',
            plan: null,
            windows: [{ name: 'seven_day', minutes: 10080, used_percent: 40, resets_at: null, stale: false }],
            credits: null,
          },
        })
      },
    )

    // As the status line script sends it: from a program on this machine, no Origin, with the setup's key.
    const setup = await (await request.post('/api/limits/claude-session/setup', { headers: OWN })).json()
    const key = (setup.command as string).split('--key ')[1]
    const soon = Math.floor(Date.now() / 1000) + 3600
    const sent = await fetch(`${APP_URL}/api/limits/claude-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Koloni-Key': key },
      body: JSON.stringify({ five_hour: { used_percentage: 53, resets_at: soon }, seven_day: { used_percentage: 93, resets_at: soon + 3 * 86400 } }),
    })
    expect(sent.status).toBe(204)

    await openFreshConversation(page)
    await rail(page, 'Models').click()
    const card = page.getByRole('button', { name: new RegExp(`^${CLI}\\s*subscription`) })
    await expect(card).toContainText('7% left this week')
    await expect(card.locator('..').locator('.hint')).toContainText('read just now, from your Claude Code session')

    // Read now, on the one whose command does not exist: answered in the page.
    const elsewhere = page.getByRole('button', { name: new RegExp(`^${ELSEWHERE}`) })
    const readNow = page.getByRole('button', { name: `Read ${ELSEWHERE}’s plan now` })
    await expect(readNow).toHaveAccessibleDescription('one short request')
    await readNow.click()
    await expect(elsewhere).toContainText('60% left this week')
    await expect(elsewhere.locator('..').locator('.hint')).toContainText('in a short run to read it')
    expect(read).toBe(1)
    await shot(page, `87-cards-${theme}`)

    // The window: what to add to Claude Code's settings, to copy.
    await card.click()
    const dialog = page.getByRole('dialog', { name: CLI })
    await dialog.getByRole('tab', { name: 'Limits' }).click()
    const part = dialog.getByRole('region', { name: 'Keep it fresh from your Claude Code sessions' })
    await expect(part).toContainText('"statusLine": {"type":"command","command":')
    await expect(part).toContainText(`koloni_statusline.py\\" --koloni http://127.0.0.1:${APP_PORT} --key ${key}`)
    await expect(part).toContainText('Add this to your Claude Code settings yourself: open your Claude Code settings file')
    await expect(part.getByRole('button', { name: 'Copy the status line setting' })).toBeVisible()
    await shot(page, `87-keep-fresh-${theme}`)
    expect((await part.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}
