import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// (Tall: the chat panel shows the whole card in its shot.)
test.use({ viewport: { width: 1440, height: 1400 } })

// Slice 91: the Lead asks for STRIPE_API_KEY on a hidden card; given, its command has it and prints it - hidden.
const VALUE = 'plain-words-given-ninety-one'

for (const theme of ['light', 'dark'] as const) {
  test(`a secret given on a hidden card reaches the command, and its output shows it masked (${theme})`, async ({ page }) => {
    writeFileSync(path.join(PROJECT_DIR, 'key91.py'), "import os\nprint('key=' + str(os.environ.get('STRIPE_API_KEY')))\n")
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const id = await openFreshConversation(page)
    expect((await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })).ok()).toBe(true)
    const chat = page.getByRole('region', { name: 'Chat' })

    await page.getByLabel('Message').fill('give the stripe key, 91')
    await page.getByRole('button', { name: 'Send' }).click()
    const card = chat.locator('.cmd-approval').filter({ hasText: 'asks for STRIPE_API_KEY' })
    await expect(card).toContainText('“to charge the test card”')
    const pieces = await card.evaluate(contrasts)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    await card.getByLabel('Value of STRIPE_API_KEY').fill(VALUE)
    await shot(card, `91-secret-card-${theme}`)
    await card.getByRole('button', { name: 'Give' }).click()

    await expect(chat.getByText('The key was there, hidden.')).toBeVisible()
    await expect(card).toHaveCount(0)
    await chat.getByRole('button', { name: /python key91\.py/ }).click()
    await expect(chat.getByText('key=***')).toBeVisible()
    expect(await page.content()).not.toContain(VALUE)
    await shot(page, `91-secret-given-${theme}`)
  })
}
