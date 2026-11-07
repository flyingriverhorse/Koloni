import { expect, type Page, test } from './fixtures'
import { LINK, OWN, contrasts, openFreshConversation, shot } from './helpers'

// Slice 63a: a team's own stages in order, which role sits in which, and the team's lead, which steps in beside another
// team. Slice 63b: on Teams & roles, each team a folded row, one open. On a team of its own, made here and deleted after:
// the ready teams that other specs read stay as they are. Nothing leaves the machine: no turn is run.
const TEAM = 'Game 63a'
type Named = { id: string; name: string }

test.afterEach(async ({ request }) => {
  for (const team of (await (await request.get('/api/teams')).json()) as Named[])
    if (team.name.startsWith(TEAM)) expect((await request.delete(`/api/teams/${team.id}`, { headers: OWN })).ok()).toBe(true)
})

const lowContrast = async (page: Page) => (await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)
/** A folded team's row opened. */
const openTeam = (page: Page, name: string) => page.getByRole('region', { name, exact: true }).getByRole('button', { name: new RegExp(`^${name}`), expanded: false }).click()

for (const theme of ['light', 'dark'] as const) {
  test(`a team's stages, who sits in which, and its lead are kept over a reload (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    // The ready teams: four stages each, their roles by kind of work, each with its lead.
    await openTeam(page, 'Web app')
    await expect(page.getByRole('region', { name: 'Web app', exact: true }).getByRole('region', { name: 'Stage 2, Build' })).toContainText('Coder')
    await shot(page, `63a-teams-ready-${theme}`)

    // A new team: the four stages of today's kinds of work, and a lead that says when it steps in.
    await page.getByRole('button', { name: 'New team' }).click()
    await page.getByLabel('New team’s name').fill(TEAM)
    await page.getByLabel('New team’s name').press('Enter')
    const team = page.getByRole('region', { name: TEAM, exact: true })
    await openTeam(page, TEAM)
    await expect(team.getByRole('region', { name: /^Stage \d/ })).toHaveCount(4)
    const leadLine = team.locator('.team-lead-row')
    await expect(leadLine).toContainText('Steps in only when this team works beside another team; else the Orchestrator runs it.')

    // A stage added, a role put in it, then in another: one stage of a team.
    await team.getByRole('button', { name: '+ Add a stage' }).click()
    await team.getByLabel('New stage’s name').fill('Playtest')
    await team.getByLabel('New stage’s name').press('Enter')
    const playtest = team.getByRole('region', { name: 'Stage 5, Playtest' })
    await playtest.getByRole('button', { name: '+ Add a role' }).click()
    await page.getByRole('combobox', { name: `Find a role to add to ${TEAM}, Playtest` }).fill('Tester')
    await page.getByRole('option', { name: /^Tester/ }).click()
    await expect(playtest.getByRole('button', { name: 'Tester', exact: true })).toBeVisible()
    await expect(page.getByText('Tester is in Playtest now.')).toBeVisible()
    const check = team.getByRole('region', { name: 'Stage 3, Check' })
    await check.getByRole('button', { name: '+ Add a role' }).click()
    await page.getByRole('option', { name: /^Tester/ }).click()
    await expect(check.getByRole('button', { name: 'Tester', exact: true })).toBeVisible()
    await expect(playtest.getByRole('button', { name: 'Tester', exact: true })).toHaveCount(0)

    // Renamed, all at once, moved up one.
    await team.getByRole('button', { name: 'Rename stage Playtest' }).click()
    await team.getByLabel('Stage’s new name').fill('Play')
    await team.getByLabel('Stage’s new name').press('Enter')
    // (Saved at once, shown as saved: ticked once the server has it.)
    await check.getByLabel('all at once').click()
    await expect(check.getByLabel('all at once')).toBeChecked()
    await team.getByRole('button', { name: 'Move Play up' }).click()
    await expect(team.getByRole('region', { name: 'Stage 4, Play' })).toBeVisible()

    // Slice 63b: a role dragged from the library into a stage joins the team there; in a narrow window, from its drawer.
    const library = page.getByRole('complementary', { name: 'Roles' })
    const plan = team.getByRole('region', { name: 'Stage 1, Plan' })
    await library.getByRole('button', { name: /^Translator/ }).dragTo(plan)
    await expect(plan.getByRole('button', { name: 'Translator', exact: true })).toBeVisible()
    await page.setViewportSize({ width: 1100, height: 900 })
    await page.getByRole('button', { name: /^Roles ▸ \d+$/ }).click()
    // (In sight before the drag: the drawer stays where it is on the window. Plan is under it until the drag
    // begins, when it slides aside.)
    await plan.scrollIntoViewIfNeeded()
    await library.getByRole('button', { name: /^Researcher/ }).dragTo(plan, { force: true })
    await expect(plan.getByRole('button', { name: 'Researcher', exact: true })).toBeVisible()
    await expect(library).toBeVisible()
    await shot(page, `63b-drawer-dropped-${theme}`)
    await page.getByRole('button', { name: 'Close the roles' }).click()
    await page.setViewportSize({ width: 1440, height: 900 })

    // Its lead: opened as a role is, its instructions changed; turned off on its team.
    await team.getByRole('button', { name: `${TEAM} lead`, exact: true }).click()
    const panel = page.getByRole('complementary', { name: `Role ${TEAM} lead` })
    await expect(panel).not.toContainText('Category')
    await panel.getByRole('tab', { name: 'Instructions' }).click()
    await panel.getByRole('button', { name: 'Edit', exact: true }).click()
    await panel.getByRole('textbox', { name: 'Instructions' }).fill('Run the playtest last.')
    await panel.getByRole('button', { name: 'Save' }).click()
    await expect(panel).toContainText('Run the playtest last.')
    await team.getByRole('switch', { name: `${TEAM} lead on` }).click()
    await expect(leadLine).toContainText(`Off: the Orchestrator always runs ${TEAM} itself`)
    await team.scrollIntoViewIfNeeded()
    await shot(page, `63a-teams-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    // Read again from the server: all of it kept, and the team still open (the browser remembers it).
    await page.goto('about:blank')
    await page.goto(LINK)
    await page.getByLabel('Message').waitFor()
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await expect(team.getByRole('region', { name: /^Stage \d/ })).toHaveText([/^1Plan/, /^2Build/, /^3Check/, /^4Play/, /^5Write & keep up/])
    await expect(check.getByRole('button', { name: 'Tester', exact: true })).toBeVisible()
    await expect(check.getByLabel('all at once')).toBeChecked()
    await expect(team.getByRole('switch', { name: `${TEAM} lead on` })).not.toBeChecked()
    const saved = ((await (await request.get('/api/teams')).json()) as { name: string; lead: { instructions: string } }[]).find(one => one.name === TEAM)
    expect(saved?.lead.instructions).toBe('Run the playtest last.')

    // The lead is its team's: not in the library.
    await expect(library.getByRole('region', { name: 'Check' })).toBeVisible()
    await expect(library.getByRole('button', { name: new RegExp(`^${TEAM} lead`) })).toHaveCount(0)
  })
}
