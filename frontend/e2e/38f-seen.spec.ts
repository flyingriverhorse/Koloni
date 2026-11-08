import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// A failed test leaves its turn asking to run a command: stopped, so the specs after it see nothing running.
test.afterEach(async ({ request }, info) => {
  if (info.status === info.expectedStatus) return
  await request.post('/api/hold', { headers: OWN })
  await request.post('/api/hold/resume', { headers: OWN })
})

/** What the rail's badge says waits now. The backend is shared with the specs before this one: it is read, never assumed. */
async function waiting(page: Page) {
  const id = await rail(page, 'Ready').getAttribute('aria-describedby')
  return id ? Number((await page.locator(`#${id}`).textContent())?.split(' ')[0]) : 0
}

/** The badge once it stopped changing: after the Board, each other chat where something waits is read on its own. */
async function steady(page: Page) {
  let last = NaN
  await expect
    .poll(async () => {
      const [was, now] = [last, await waiting(page)]
      last = now
      return was === now
    }, { intervals: [1000], timeout: 15_000 })
    .toBe(true)
  return last
}

/** Every piece of text in it against what it stands on: 4.5 or more. */
async function readable(root: Locator) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThan(0)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

for (const theme of ['light', 'dark'] as const) {
  test(`what waits out of sight, ${theme}: the badge counts it, a toast says it once and opens it; archived, a conversation comes back whole`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // (Ends in "slowly": the scripted model takes a moment over each step, and asks to run a command.)
    const title = `seen ${theme} ${Date.now()} run it slowly`
    const chat = page.getByRole('region', { name: 'Chat' })
    const toasts = page.locator('.toasts')
    await openFreshConversation(page)
    // How things stand before: the Board, read on its own page.
    // (The badge counts every project's: /api/board, not this project's /projects/…/board.)
    const read = page.waitForResponse(r => new URL(r.url()).pathname === '/api/board' && r.ok())
    await rail(page, 'Board').click()
    await read
    const before = await steady(page)
    await rail(page, 'Canvas').click()

    // The turn starts here, and the user goes to another page before it asks.
    await page.getByLabel('Message').fill(title)
    await page.getByRole('button', { name: 'Send' }).click()
    await rail(page, 'Board').click()
    await expect(toasts.getByText(`Orchestrator waits for you · ${title}`)).toBeVisible({ timeout: 15_000 })
    await expect.poll(() => waiting(page)).toBe(before + 1)
    await expect(rail(page, 'Ready')).toHaveAccessibleName('Ready')
    await expect(toasts.locator('.toast')).toHaveCount(1)
    await readable(toasts)
    await readable(page.locator('.rail-badge'))
    await shot(page, `38f2-toast-${theme}`)

    // Open goes there; the card is decided, and what waits goes down again.
    await toasts.locator('.toast', { hasText: title }).getByRole('button', { name: 'Open' }).click()
    await expect(chat.getByText('Run this command?')).toBeVisible()
    await chat.getByRole('button', { name: 'Reject' }).click()
    await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 15_000 })
    await expect.poll(() => waiting(page)).toBe(before)
    // Its turn ended on screen: no toast for it.
    await expect(toasts.locator('.toast', { hasText: title })).toHaveCount(0)
    // A plain answer (slice 107): nothing changed, nobody opened, nothing known spent - nothing under it.
    await expect(chat.getByRole('region', { name: 'What it did' })).toHaveCount(0)

    // Archived, it leaves the list for its "Archived" part; nothing of it goes, and it comes back.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Chats', exact: true }).click()
    await page.getByRole('searchbox', { name: 'Search conversations' }).fill(title)
    await page.getByRole('button', { name: `Archive ${title}` }).click()
    const archived = page.getByRole('region', { name: 'Archived' })
    await expect(archived.getByRole('button', { name: new RegExp(`^${title}`) })).toBeVisible()
    await readable(page.locator('.conv-page'))
    await shot(page, `38f2-archived-${theme}`)
    await archived.getByRole('button', { name: `Unarchive ${title}` }).click()
    await expect(archived).toHaveCount(0)
    await page.getByRole('button', { name: new RegExp(`^${title}`) }).click()
    await expect(chat.getByText(title, { exact: true })).toBeVisible()
  })
}
