import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail } from './helpers'

// tek-ev §1: Ready for you. Two chats each ask to run a command; the top bar's pill opens the panel - this chat's card
// first, the other chat's under Elsewhere - and a Run once there is the chat's own decision: the card is answered in
// its chat too. The page has the same list. Nothing leaves the machine: the fake model plays it.
// (READY_SHOTS: a folder to keep the panel's and the page's pictures in.)
const SHOTS = process.env.READY_SHOTS

async function asking(page: Page, words: string) {
  const id = await openFreshConversation(page)
  // (Ask before a command. Its first message names it: its row is found by these words.)
  const set = await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })
  expect(set.ok()).toBe(true)
  await page.getByLabel('Message').fill(`run the tests, ${words}`)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Run this command?')).toBeVisible({ timeout: 20_000 })
  return id
}

const commandOf = async (page: Page, id: string) => ((await (await page.request.get(`/api/conversations/${id}`)).json()).commands as { status: string }[])[0]?.status

for (const theme of ['light', 'dark'] as const) {
  test(`Ready for you (${theme}): the pill opens the panel, this chat first; Run once there answers the other chat's card`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const first = `ready one ${theme} ${Date.now()}`
    const second = `ready two ${theme} ${Date.now()}`
    const one = await asking(page, first)
    const two = await asking(page, second)
    const chat = page.getByRole('region', { name: 'Chat' })

    // The pill: how many wait anywhere (other specs' chats may wait too); the chat's line says the rest are elsewhere.
    const pill = page.locator('.ready-pill')
    await expect(pill).toHaveText(/^\d+ wait$/)
    await expect(chat.locator('.ready-line')).toContainText(/\d+ more waits? elsewhere/, { timeout: 15_000 })
    await pill.click()
    const panel = page.getByRole('complementary', { name: /^Ready for you · \d+$/ })
    await expect(panel).toBeFocused()
    const here = panel.getByRole('heading', { name: 'This chat · 1' })
    const elsewhere = panel.getByRole('heading', { name: /^Elsewhere · \d+$/ })
    await expect(here).toBeVisible()
    expect(await here.evaluate((h, rest) => Boolean(h.compareDocumentPosition(rest!) & Node.DOCUMENT_POSITION_FOLLOWING), await elsewhere.elementHandle())).toBe(true)
    const row = panel.getByRole('group', { name: new RegExp(first) })
    await expect(row).toBeVisible({ timeout: 15_000 })
    // Decision 1: the whole command beside Run once, never cut.
    const shown = row.locator('pre.cmd-approval-command')
    await expect(shown).toHaveText('python check.py')
    expect(await shown.evaluate(pre => pre.scrollWidth <= pre.clientWidth && pre.scrollHeight <= pre.clientHeight)).toBe(true)
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true })
      await page.screenshot({ path: path.join(SHOTS, `panel-${theme}.png`) })
    }

    // The page: the same list, oldest first, with its filters.
    await panel.getByRole('button', { name: 'Open all as a page →' }).click()
    await expect(panel).toBeHidden()
    const list = page.locator('.ready-page')
    await expect(list.getByRole('heading', { name: 'Ready for you' })).toBeVisible()
    await expect(list.getByRole('group', { name: 'Show' }).getByRole('button', { name: /^Chats · \d+$/ })).toBeVisible()
    await expect(list.getByRole('group', { name: new RegExp(second) })).toBeVisible()
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `page-${theme}.png`) })
    // Open chat on the first chat's row: that chat on the canvas, and the panel at its card - This chat now.
    const firstRow = list.getByRole('group', { name: new RegExp(first) })
    const command = await page.request.get(`/api/conversations/${one}`).then(async read => (await read.json()).commands[0].id as string)
    await firstRow.getByRole('button', { name: 'Open chat' }).click()
    await expect(panel.getByRole('heading', { name: 'This chat · 1' })).toBeVisible()
    await expect(panel.locator(`#waiting-${command}`)).toBeInViewport()
    await expect(chat.getByText('Run this command?').first()).toBeVisible()

    // Run once on the other chat's card, now under Elsewhere: it is that chat's decision.
    const other = panel.getByRole('group', { name: new RegExp(second) })
    await other.getByRole('button', { name: 'Run once' }).click()
    await expect(other).toHaveCount(0, { timeout: 15_000 })
    await expect.poll(() => commandOf(page, two)).not.toBe('proposed')
    // And this chat's, from the panel: gone from the chat as well.
    await panel.getByRole('region', { name: 'Needs your answer' }).getByRole('button', { name: 'Run once' }).click()
    await expect(chat.getByText('Run this command?')).toHaveCount(0, { timeout: 15_000 })
    await expect(chat.getByText('The tests pass.')).toBeVisible({ timeout: 15_000 })
    await expect.poll(() => commandOf(page, one)).not.toBe('proposed')
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
  })
}
