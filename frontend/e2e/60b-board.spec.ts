// Slice 60b in the browser, as tek-ev §2 left it: the Board is now - At work (a chat that runs, one whose agent asks
// you), Ended today (one done, one stopped), the older ones folded - each row saying what it can; what waits for you
// is one line to Ready for you. Readable in both themes, and stacked on a narrow window.
import { expect, test, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const DONE = 'hello, board of 60b'
const ASKS = 'run the slow job, 60b asks'
const STOPPED = 'run the slow job, 60b stops'
const WORKS = 'run slow.py for 60b'

const lastRun = async (page: Page, id: string) => (await (await page.request.get(`/api/conversations/${id}`)).json()).runs.at(-1)

async function start(page: Page, message: string, fullAuto = false) {
  const id = await openFreshConversation(page)
  if (fullAuto) expect((await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })).ok()).toBe(true)
  await page.getByLabel('Message').fill(message)
  await page.getByRole('button', { name: 'Send' }).click()
  return id
}

test('the board is now: what works (an agent that asks you too), what ended today, a line to Ready for you; both themes read', async ({ page }) => {
  test.setTimeout(90_000)
  const chat = page.getByRole('region', { name: 'Chat' })
  const done = await start(page, DONE)
  // One that never ran: folded under the older ones.
  const project = (await (await page.request.get('/api/projects')).json())[0].id
  expect((await page.request.post(`/api/projects/${project}/conversations`, { headers: OWN })).ok()).toBe(true)
  await expect.poll(async () => (await lastRun(page, done))?.status, { timeout: 20_000 }).toBe('completed')
  const asks = await start(page, ASKS)
  await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 15_000 })
  const stopped = await start(page, STOPPED)
  await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 15_000 })
  await chat.getByRole('button', { name: 'Stop' }).click()
  await expect.poll(async () => (await lastRun(page, stopped))?.status, { timeout: 15_000 }).toBe('cancelled')
  // A command that runs half a minute without asking: its conversation is at work meanwhile.
  const works = await start(page, WORKS, true)
  const column = (name: string) => page.getByRole('region', { name })
  const card = (name: string, title: string) => column(name).getByRole('listitem', { name: title })

  try {
    // Checked once, while it runs; the shots below take it as it is by then.
    await rail(page, 'Board').click()
    await expect(card('At work', WORKS)).toContainText(/ago/, { timeout: 15_000 })
    await expect(card('At work', WORKS).locator('.board-agent').first()).toContainText('working')
    await expect(page.getByRole('status').filter({ hasText: 'agent' })).toHaveText(/agents? at work/)
    for (const theme of ['light', 'dark'] as const) {
      await page.evaluate(chosen => localStorage.setItem('koloni-theme', chosen), theme)
      await page.reload()
      await rail(page, 'Board').click()
      for (const name of ['At work', 'Ended today']) await expect(column(name)).toBeVisible()
      // What the command asks is Ready for you's: here one line leads there, and the row says its agent waits.
      await expect(page.locator('.ready-line')).toContainText(/^\d+ things? waits? for you/)
      await expect(card('At work', ASKS).locator('.board-agent .status')).toHaveText('waits for you')
      await expect(card('Ended today', STOPPED).locator('.board-facts')).toHaveText(/^stopped\s*\d+ agents? · .+$/)
      // a finished row: its agents and when (its model is its chat's, its tokens are Usage's)
      await expect(card('Ended today', DONE).locator('.board-facts')).toHaveText(/^1 agent · .+$/)
      await expect(column('Ended today').locator('details.board-older > summary')).toHaveText(/^\d+ older$/)
      await expect(column('Ended today').getByRole('list', { name: 'Older' }).getByRole('listitem', { name: 'New conversation' }).first()).toBeHidden()
      // The keyboard reaches a row's title, which opens it.
      await card('Ended today', DONE).getByRole('button', { name: DONE }).focus()
      await expect(card('Ended today', DONE).getByRole('button', { name: DONE })).toBeFocused()

      const pieces = await page.locator('.memory-page').evaluate(contrasts)
      expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
      await shot(page, `60b-board-${theme}`)
    }

    // On a narrow window the sections stand one under another.
    await page.setViewportSize({ width: 600, height: 900 })
    const [work, ended] = await Promise.all(['At work', 'Ended today'].map(name => page.getByRole('region', { name }).boundingBox()))
    expect(ended!.y).toBeGreaterThan(work!.y + work!.height - 1)
    await shot(page, '60b-board-narrow')

    // A row's title opens its conversation.
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.getByRole('region', { name: 'Ended today' }).getByRole('button', { name: DONE }).click()
    await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  } finally {
    // Nothing is left at work, waiting or stopped for the specs after this one: each ends on a turn done.
    for (const id of [works, asks, stopped]) {
      const run = await lastRun(page, id)
      if (!['completed', 'failed', 'cancelled', 'interrupted'].includes(run?.status)) await page.request.post(`/api/runs/${run.id}/cancel`, { headers: OWN })
      await page.request.post(`/api/conversations/${id}/messages`, { data: { content: 'hello again' }, headers: OWN })
      await expect.poll(async () => (await lastRun(page, id))?.status, { timeout: 20_000 }).toBe('completed')
    }
  }
})

test('a long section scrolls in itself: the page keeps its height and the heading stays on top', async ({ page }) => {
  // Enough conversations that never ran to make the older fold longer than the window.
  for (let i = 0; i < 14; i++) await openFreshConversation(page)
  await rail(page, 'Board').click()
  const done = page.getByRole('region', { name: 'Ended today' })
  await done.locator('summary', { hasText: /^\d+ older$/ }).click()
  const box = (await done.boundingBox())!
  expect(box.y + box.height).toBeLessThanOrEqual(900)
  expect(await done.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
  await done.evaluate(el => el.scrollTo(0, el.scrollHeight))
  await expect(done.getByRole('heading', { name: /Ended today/ })).toBeInViewport()
})
