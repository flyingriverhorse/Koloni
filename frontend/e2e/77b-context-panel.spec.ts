// K-baglam-paneli in the browser: the lead's context in the top bar opens each agent's of the turn, and Compact now
// is pressed there - in a 1280×720 window, clear of the floating chat's message box.
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, openFreshConversation, say, shot } from './helpers'

test.use({ viewport: { width: 1280, height: 720 } })

const lead = async (request: APIRequestContext) =>
  (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Lead')

// The backend is shared with the other specs: the Lead's window is put back.
async function putBack({ request }: { request: APIRequestContext }) {
  await request.post(`/api/roles/${(await lead(request)).id}/reset`, { headers: OWN })
}
test.beforeEach(putBack)
test.afterEach(putBack)

for (const theme of ['light', 'dark'] as const) {
  test(`the top bar's context opens each agent's, and Compact now summarises the lead (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // A window the fake model's 120 tokens fill to 12%.
    expect((await request.patch(`/api/roles/${(await lead(request)).id}`, { data: { context_window: 1000 }, headers: OWN })).ok()).toBe(true)
    await openFreshConversation(page)
    await say(page, 'Compact me.', 'It prints hi.')

    const trigger = page.locator('.topbar').getByRole('button', { name: 'context 12%' })
    await trigger.click()
    const panel = page.getByRole('dialog', { name: 'Each agent’s context' })
    await expect(panel).toBeFocused()
    const row = panel.getByRole('listitem').filter({ hasText: 'Lead' })
    await expect(row).toContainText('12%')
    await expect(row).toContainText('120 / 1,000')
    // Inside the window, and clear of the floating chat's message box.
    const [shown, box] = [(await panel.boundingBox())!, (await page.getByLabel('Message').boundingBox())!]
    expect(shown.y + shown.height).toBeLessThanOrEqual(720)
    expect(shown.y + shown.height <= box.y || shown.x >= box.x + box.width).toBe(true)

    await row.getByRole('button', { name: 'Compact now' }).click()
    await expect(row.getByText('Compacted: 2 messages more summarised.')).toBeVisible()
    await shot(page, `77b-context-panel-${theme}`)

    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(trigger).toBeFocused()
  })
}
