import { expect, type Page, test } from './fixtures'
import { contrasts, openFreshConversation, say, shot } from './helpers'

// Slice 84b-1: "Teams for this chat", over the canvas's top right. In Manual the user picks a team and its recipe; the
// pick stays over a reload, and the Lead may then open only that team's roles - a Coder, which Docs has not, is
// refused, and the chat says why. Nothing leaves the machine: the fake model asks for the Coder.
const lowContrast = async (page: Page) => (await page.locator('.chat-teams-panel').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)
const window = (page: Page) => page.getByRole('dialog', { name: 'Teams for this chat' })
const open = (page: Page) => page.getByRole('button', { name: /^Teams for this chat/ }).click()

for (const theme of ['light', 'dark'] as const) {
  test(`Manual: a team and its recipe are kept, and a role outside it is refused (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    // (The Lead hands code on: asked to make the farewell, it asks for a Coder - not named by the user, who would let it in.)
    await openFreshConversation(page, { leadWrites: false })

    await page.getByRole('button', { name: 'Teams for this chat: No teams' }).click()
    await window(page).getByRole('radio', { name: /Manual/ }).click()
    await expect(window(page)).toContainText('No team picked: the Orchestrator calls any role')
    await window(page).getByRole('button', { name: '+ Add a team with a recipe' }).click()
    await window(page).getByLabel('Team 1').selectOption({ label: 'Docs' })
    await expect(window(page).getByLabel('Recipe for Docs')).toBeVisible()
    await window(page).getByLabel('Recipe for Docs').selectOption({ label: 'Feature' })
    await expect(page.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' })).toBeVisible()
    await shot(page, `84b-teams-manual-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    // Kept: read again from the server after a reload.
    await page.reload()
    await page.getByLabel('Message').waitFor()
    await open(page)
    await expect(window(page).getByLabel('Team 1').locator('option:checked')).toHaveText('Docs')
    await expect(window(page).getByLabel('Recipe for Docs').locator('option:checked')).toHaveText('Feature')
    await page.keyboard.press('Escape')

    // The Lead asks for a Coder: Docs runs Feature (84b-2), whose first step is the Spec writer's, so it is refused
    // and the chat says why.
    await say(page, 'make farewell', /Feature recipe of Docs is at its Write the spec step/)
    await expect(page.locator('.react-flow__node-agent').filter({ hasText: 'Coder' })).toHaveCount(0)
    await shot(page, `84b-teams-refused-${theme}`)

    // An agent's window stands in the same corner: the button goes to its left, both in sight.
    await page.locator('.react-flow__node-agent', { hasText: 'Orchestrator' }).locator('.node-title').first().click()
    await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
    const agentWindow = page.getByRole('region', { name: 'Agent window' })
    await expect(agentWindow).toBeVisible()
    const button = await page.getByRole('button', { name: /^Teams for this chat/ }).boundingBox()
    expect(button!.x + button!.width).toBeLessThanOrEqual((await agentWindow.boundingBox())!.x)
    await shot(page, `84b-teams-beside-agent-window-${theme}`)
  })
}
