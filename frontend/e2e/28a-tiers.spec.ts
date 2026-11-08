import { expect, test } from './fixtures'
import { contrasts, editRole, openAgentFold, openFreshConversation, rail, roleRow, shot, windowFromPanel } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test('models are given a tier, a role asks for one, and a lead’s model follows how hard the message is', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const agents = page.getByRole('button', { name: 'Agents', exact: true })
  const save = page.getByRole('button', { name: 'Save' })

  // The user says how strong two models of the default provider are.
  await rail(page, 'Models').click()
  await page.getByRole('button', { name: /^Local/ }).click()
  const rows = page.locator('.model-table tbody tr:not(.model-facts)')
  const had = await rows.count()
  // Each is named once, when added, and its tier is saved as it is chosen (slice 81a).
  for (const [name, tier] of [['fake-quick', 'fast'], ['fake-strong', 'strongest']] as const) {
    await page.getByRole('button', { name: 'Add a model' }).click()
    await page.getByLabel('New model’s name').fill(name)
    await page.getByLabel('New model’s name').press('Enter')
    await page.getByLabel(`Tier of ${name}`).selectOption(tier)
    await expect(page.getByRole('status').filter({ hasText: `${name}: ${tier}.` })).toBeVisible()
  }
  // (What a tier is for is behind the ⓘ: one click away.)
  await page.locator('.hint', { hasText: 'A model with no tier is only ever picked by name' }).getByRole('button', { name: 'About this' }).click()
  await expect(page.getByText(/A model with no tier is only ever picked by name/)).toBeVisible()
  await page.getByLabel('Tier of fake-strong').scrollIntoViewIfNeeded()
  await shot(page, '28a-model-tiers')
  await page.keyboard.press('Escape') // the ⓘ
  await page.keyboard.press('Escape') // the window

  // The built-in roles are there, each with no tier of its own: the Lead picks one for each job (slice 81b).
  await agents.click()
  for (const name of ['Debugger', 'Architect', 'Security reviewer', 'Docs writer', 'Refactorer']) {
    await roleRow(page, name).click()
    await expect(page.getByRole('complementary', { name: `Role ${name}` })).toContainText('Which modelOrchestrator · fast–strongest')
  }
  await editRole(page, 'Docs writer', 'tiers')
  await expect(page.getByRole('radio', { name: 'Orchestrator', exact: true })).toBeChecked()
  // With no tier given: the balanced model, else the conversation's (none is balanced here).
  await expect(page.getByText(/^Runs on/)).toContainText('no model in your team guide that may be picked for it has the balanced tier')
  await editRole(page, 'Reviewer', 'tiers')
  await expect(page.getByText('It picks a tier for each job, inside this range, and says why.')).toBeVisible()
  await page.getByRole('radio', { name: 'One tier' }).check()
  await page.getByRole('radio', { name: 'Strongest' }).check()
  await page.getByRole('radiogroup', { name: 'Who picks it?' }).scrollIntoViewIfNeeded()
  await shot(page, '28a-role-tier')
  await save.click()
  const reviewer = page.getByRole('complementary', { name: 'Role Reviewer' })
  await expect(reviewer).toContainText('Which modelAlways strongest')

  await rail(page, 'Canvas').click()

  // The lead's model follows the message: the choice says what it costs, and what it overrides.
  await chat.getByRole('button', { name: /^Model: / }).click()
  // What it costs and what it overrides stand under the box; how the Lead's model is then chosen is the rest of
  // that note, behind ⓘ beside it - and opening it is not ticking the box.
  await expect(chat.getByText(/^One more request for each message you send: a fast model of your team guide is sent your message/)).toBeVisible()
  await expect(chat.getByText(/It overrides the Orchestrator role’s own model and tier\. A trigger’s message does not use it\./)).toBeVisible()
  await chat.locator('.hint', { hasText: 'The Orchestrator then runs on your first fast' }).getByRole('button', { name: 'About this' }).click()
  await expect(chat.getByText(/^The Orchestrator then runs on your first fast/)).toBeVisible()
  await chat.getByText(/^The Orchestrator then runs on your first fast/).click()
  await expect(chat.getByLabel(/Orchestrator model: automatic/)).not.toBeChecked()
  await chat.getByLabel(/Orchestrator model: automatic/).check()
  await shot(chat, '28a-lead-automatic')
  await chat.getByRole('button', { name: 'Use this model' }).click()
  await expect(chat.getByRole('button', { name: /^Model: Orchestrator: automatic · / })).toBeVisible()

  // The fast model says this one is hard: the lead of the turn runs on the strongest model,
  // and its node says how that was decided - a model's guess, in that model's words.
  await page.getByLabel('Message').fill('hello, everything at once')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  const lead = page.locator('.react-flow__node-agent').first()
  await expect(lead).toContainText('Local · fake-strong')
  // (its tier and how it was chosen are in the side panel: the node is three lines - the user's, 5 Nov)
  // the question itself is nobody's message: the conversation holds the user's and the lead's
  await expect(chat.getByText('hard: it touches the whole project')).toHaveCount(0)
  await shot(page, '28a-lead-node')
  // in full in its window, under Details
  await lead.click()
  const own = await windowFromPanel(page)
  await openAgentFold(own, 'Details')
  await expect(own.getByText('Model', { exact: true }).locator('xpath=following-sibling::dd[1]')).toContainText(
    'fake-strong · automatic, by Local · fake-quick’s guess: “hard: it touches the whole project”',
  )
  await own.getByRole('button', { name: 'Close agent window' }).click()

  // An easy one runs on the fast model.
  await page.getByLabel('Message').fill('hello again')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.react-flow__node-agent').first()).toContainText('Local · fake-quick')

  // Put back, so that later runs start from the defaults: the role's tier, and the models' tiers.
  await agents.click()
  await editRole(page, 'Reviewer', 'tiers')
  await page.getByRole('radio', { name: 'Fast' }).check()
  await save.click()
  await expect(reviewer).toContainText('Which modelAlways fast')
  await editRole(page, 'Reviewer', 'tiers')
  await page.getByRole('button', { name: 'Reset to default' }).click()
  await expect(page.getByRole('radio', { name: 'Orchestrator', exact: true })).toBeChecked() // as it came (slice 81b)
  await rail(page, 'Models').click()
  await page.getByRole('button', { name: /^Local/ }).click()
  await page.getByRole('button', { name: 'Remove fake-strong' }).click()
  await page.getByRole('button', { name: 'Remove fake-quick' }).click()
  await expect(rows).toHaveCount(had)
})
