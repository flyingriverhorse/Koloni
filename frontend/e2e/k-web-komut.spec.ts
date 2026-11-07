import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, OWN, shot } from './helpers'

// K-web-komut: with a web tool off on the Tools page, a command that reaches the internet is asked on the usual card at
// Full auto too, and the card says why. The fake Lead's `curl` is turned down: nothing leaves the machine.
test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  expect((await request.put('/api/builtin-tools/http_request', { headers: OWN, data: { on: true } })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  test(`web off: curl at Full auto is a card that says why (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    expect((await page.request.put('/api/builtin-tools/http_request', { headers: OWN, data: { on: false } })).ok()).toBe(true)
    const id = await openFreshConversation(page)
    const level = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })
    expect((await level.json()).permission_mode).toBe('full_auto')
    await page.getByLabel('Message').fill('fetch the page, k-web-komut')
    await page.getByRole('button', { name: 'Send' }).click()

    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 20_000 })
    const card = chat.locator('.cmd-approval').filter({ hasText: 'curl https://example.com' })
    await expect(card).toContainText('web is off on the Tools page (http_request is off); this command reaches the internet: curl')
    await expect(card.getByRole('button', { name: /Always run/ })).toHaveCount(0)
    await shot(card, `k-web-komut-card-${theme}`)
    expect((await card.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    await card.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText('Left the page alone.')).toBeVisible()
  })
