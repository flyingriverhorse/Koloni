import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, projectSettings, saveSettings } from './helpers'

// K-vekil-karar: while you're away, the Lead answers what it safely can. The setting is turned on in the chat's
// settings; a Coder is to be opened, and then asks which greeting: the Lead (the fake model) decides both, each with
// a reason, and they are under "Decided for you" on Ready for you's panel - OK on the one that cannot be undone, Change on the
// Coder's while it is still at work. Nothing leaves the machine.
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'vk-shots')

for (const theme of ['light', 'dark'] as const) {
  test(`the Lead decides for you while you are away, and you look when you are back (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    const id = await openFreshConversation(page, { leadWrites: false })
    mkdirSync(SHOTS, { recursive: true })

    // The setting: every chat's, in Settings › This project › Asking and away, with the minutes before the Lead answers (0: at once).
    const settings = await projectSettings(page, /^Asking and away/)
    await expect(settings.getByLabel('When you’re away')).toHaveValue('waits')
    await settings.getByLabel('When you’re away').selectOption('lead')
    await settings.getByLabel('Minutes before the Orchestrator answers').fill('0')
    await settings.screenshot({ path: path.join(SHOTS, `setting-${theme}.png`) })
    await saveSettings(page)
    await expect.poll(async () => (await (await request.get(`/api/conversations/${id}`)).json()).conversation.when_away).toBe('lead')

    // A Coder to open (asked at this level), then its question: both the Lead's to answer.
    await page.getByLabel('Message').fill('vk: greet while I am away')
    await page.getByRole('button', { name: 'Send' }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    // (To look at, not waiting: the pill says "2 decided" - or, where other chats of the run wait, how many do;
    // the panel has the two under This chat.)
    const pill = page.locator('.ready-pill')
    await expect(pill).toHaveText(/^(2 decided|\d+ waits?)$/, { timeout: 20_000 })
    await pill.click()
    const panel = page.getByRole('complementary', { name: /^Ready for you/ })
    await expect(panel.getByRole('heading', { name: 'This chat · 0' })).toBeVisible()
    const decided = panel.getByRole('region', { name: /Decided for you while you were away/ })
    await expect(decided).toContainText('2 ·')
    const items = decided.locator('.decided-item')
    const opening = items.filter({ hasText: 'Open Coder for this task?' })
    const greeting = items.filter({ hasText: 'Coder asked: Which greeting should I use?' })
    await expect(opening).toContainText('Orchestrator chose Approve')
    await expect(opening).toContainText('“It is the first choice, and nothing asks for another.”')
    await expect(opening).toContainText("can't be undone: the next step ran")
    await expect(greeting).toContainText('Orchestrator chose hello')
    // (Nothing of it waits: the list's other parts are empty.)
    await expect(panel.getByRole('region', { name: 'Needs your answer' })).toHaveCount(0)
    await panel.screenshot({ path: path.join(SHOTS, `decided-${theme}.png`) })
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // Change, while the Coder still works: your choice goes to it.
    await greeting.getByRole('button', { name: 'Change → hey' }).click()
    await expect(greeting).toHaveCount(0)
    await opening.getByRole('button', { name: 'OK' }).click()
    await expect(decided).toHaveCount(0)
    await panel.getByRole('button', { name: 'Close Ready for you' }).click()
    await expect(chat.getByText('The Coder went with your hey.')).toBeVisible({ timeout: 20_000 })
  })
}
