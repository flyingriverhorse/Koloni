import { expect, test, type APIRequestContext } from './fixtures'
import { appSettings, OWN, openAgentFold, openFreshConversation, rail, say, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const lead = async (request: APIRequestContext) =>
  (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Lead')

// The backend is shared with the other specs: the threshold and the Lead's window are put back.
async function putBack({ request }: { request: APIRequestContext }) {
  await request.put('/api/compaction', { headers: OWN, data: { compact_at: 75 } })
  await request.post(`/api/roles/${(await lead(request)).id}/reset`, { headers: OWN })
}
test.beforeEach(putBack)
test.afterEach(putBack)

for (const theme of ['light', 'dark'] as const) {
  test(`the threshold is set in Settings › The app, the header says how full the lead is, and Compact now summarises it (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // A window the fake model's 120 tokens fill to 12% (the fake is no llama-server).
    expect((await request.patch(`/api/roles/${(await lead(request)).id}`, { data: { context_window: 1000 }, headers: OWN })).ok()).toBe(true)
    await openFreshConversation(page)

    // The threshold: one setting of every project, in Settings › The app, with what it does not apply to behind ⓘ.
    await appSettings(page, 'Agents')
    const settings = page.getByRole('form', { name: 'App settings' })
    const field = settings.getByLabel('Summarise a long context at (%)')
    await expect(field).toHaveValue('75')
    await expect(field).toHaveAccessibleDescription(/passes this much of its model’s window, the older part is summarised before its next step\.$/)
    await field.fill('90')
    await settings.getByRole('button', { name: 'Save' }).click()
    await expect(settings.getByRole('status')).toHaveText('Saved')
    expect(await (await request.get('/api/compaction')).json()).toEqual({ compact_at: 90 })
    await shot(page, `77a-compact-setting-${theme}`)
    await page.getByRole('button', { name: 'Close settings' }).click()

    // A short turn: nothing summarised by itself. The header says how full its lead is.
    await say(page, 'Compact me.', 'It prints hi.')
    await expect(page.locator('.topbar')).toContainText('context 12%')

    await rail(page, 'Canvas').click()
    const node = page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Orchestrator/ }) }).last()
    await expect(node).not.toContainText('summarised')
    await node.locator('.node-title').click()
    await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
    const own = page.getByRole('region', { name: 'Agent window' })
    // (with its working state, under Details)
    await openAgentFold(own, 'Details')
    await own.getByRole('button', { name: 'Compact now' }).click()
    await expect(own.getByText('Compacted: 2 messages more summarised.')).toBeVisible()
    await expect(own.getByText('2 messages summarised for its model')).toBeVisible()
    // (Said in its window, not on its node: three lines - the user's, 5 Nov.)
    await expect(node).not.toContainText('summarised')
    await shot(page, `77a-compact-now-${theme}`)

    // Its next turn's lead goes on from the summary: the fake says so only when it is sent it.
    await rail(page, 'Chats').click()
    // (The one open: the other theme's run made one of the same name.)
    await page.getByRole('button', { name: /^Compact me\./ }).and(page.locator('[aria-current="true"]')).click()
    await say(page, 'And on?', 'Going on from the summary.')
  })
}
