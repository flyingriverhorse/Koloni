import { expect, type Page, test } from './fixtures'
import { contrasts, openFreshConversation, shot } from './helpers'

// K-tarifsiz: in Manual a chat runs a team by its default recipe, or with No recipe in this chat only - the team keeps
// its default for other chats. The choice stays over a reload. Nothing leaves the machine.
const lowContrast = async (page: Page) => (await page.locator('.chat-teams-panel').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)
const window = (page: Page) => page.getByRole('dialog', { name: 'Teams for this chat' })

for (const theme of ['light', 'dark'] as const) {
  test(`Manual: a team runs with No recipe in this chat, its default kept (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page, { leadWrites: false })

    await page.getByRole('button', { name: 'Teams for this chat: No teams' }).click()
    await window(page).getByRole('radio', { name: /Manual/ }).click()
    await window(page).getByRole('button', { name: '+ Add a team with a recipe' }).click()
    await window(page).getByLabel('Team 1').selectOption({ label: 'Docs' })
    const recipe = window(page).getByLabel('Recipe for Docs')
    await expect(recipe.locator('option:checked')).toHaveText('its default (Docs)')
    await recipe.selectOption({ label: 'No recipe' })
    await expect(recipe.locator('option:checked')).toHaveText('No recipe')
    await shot(page, `k-tarifsiz-no-recipe-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    await page.reload()
    await page.getByLabel('Message').waitFor()
    await page.getByRole('button', { name: /^Teams for this chat/ }).click()
    await expect(window(page).getByLabel('Recipe for Docs').locator('option:checked')).toHaveText('No recipe')
  })
}
