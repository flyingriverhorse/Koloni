import { expect, test } from './fixtures'
import { OWN, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// The backend is shared with the specs after this one: whatever happens here, nothing is left held.
test.afterEach(async ({ page }) => {
  expect((await page.request.post('/api/hold/resume', { headers: OWN })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const) {
  test(`Stop everything, ${theme}: it asks, stops the turn, lists it, the bar says Held, and Resume lets go`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // (Ends in "slowly": the scripted Lead asks to run a command, and its turn waits for the answer.)
    const title = `hold ${theme} ${Date.now()} run it slowly`
    const chat = page.getByRole('region', { name: 'Chat' })
    await openFreshConversation(page)
    await page.getByLabel('Message').fill(title)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 15_000 })

    const bar = page.locator('.topbar')
    await bar.getByRole('button', { name: 'Stop everything' }).click()
    const ask = page.getByRole('dialog', { name: 'Stop everything' })
    await expect(ask).toContainText(/turns? running in your chats will stop/)
    await expect(ask).toContainText('Your own messages still run')
    await shot(page, `hold-confirm-${theme}`)
    await ask.getByRole('button', { name: 'Stop everything' }).click()

    const held = page.getByRole('dialog', { name: 'Everything is held' })
    await expect(held.getByRole('region', { name: 'Stopped' }).getByRole('button', { name: title })).toBeVisible()
    await expect(held).toContainText('times missed while held are skipped')
    await expect(chat.getByText('Run this command?')).toHaveCount(0)
    await shot(page, `hold-stopped-${theme}`)
    await page.keyboard.press('Escape')
    await expect(held).toHaveCount(0)
    const resume = bar.getByRole('button', { name: 'Held · Resume' })
    await expect(resume).toBeVisible()
    await shot(bar, `hold-bar-${theme}`)

    await resume.click()
    await held.getByRole('button', { name: 'Resume' }).click()
    await expect(bar.getByRole('button', { name: 'Stop everything' })).toBeVisible()
    expect((await (await page.request.get('/api/hold')).json()).held).toBe(false)
  })

  test(`the same error twice says ×2 on one toast and the bell lists both, ${theme}`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // No scripted model turn fails: the Board is answered here, with a chat out of sight whose two turns fail.
    const steps = ['running', 'failed', 'running', 'failed'] as const
    let first: number | null = null
    await page.route('**/api/board', async route => {
      // (By time, not by request: the page reads the Board more than once as it opens; it then reads it every 5 s.)
      first ??= Date.now()
      const at = Math.min(Math.floor((Date.now() - first) / 4000), steps.length - 1)
      const turn = { id: `t${at >> 1}`, status: steps[at], started_at: null, ended_at: null, agents: 0, provider_name: null, model_id: null, tokens: null, plan_waits: false }
      const chat = { conversation_id: 'out-of-sight', title: 'Nightly look', agents: [], merges_pending: 0, turn, project_id: null }
      await route.fulfill({ json: { backlog_waiting: 0, limit: null, running: 0, conversations: [chat], conflicts: [] } })
    })
    await openFreshConversation(page)
    const toasts = page.locator('.toasts')
    await expect(toasts.locator('.toast', { hasText: 'Failed · Nightly look ×2' })).toBeVisible({ timeout: 30_000 })
    await expect(toasts.locator('.toast')).toHaveCount(1)
    await shot(page, `toast-times-two-${theme}`)
    await page.locator('.topbar').getByRole('button', { name: 'Notifications' }).click()
    const list = page.getByRole('dialog', { name: 'Recent notifications' })
    await expect(list.getByRole('listitem')).toHaveCount(2)
    await shot(page, `toast-recent-${theme}`)
  })
}
