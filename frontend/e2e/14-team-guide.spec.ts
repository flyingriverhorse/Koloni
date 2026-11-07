import { expect, test, type Page } from './fixtures'
import { openAgentFold, openFreshConversation, windowFromPanel } from './helpers'
import { MODEL_URL } from './paths.mjs'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('the user puts a provider in the team guide, the lead picks it for a sub-agent, and the card says so', async ({ page }) => {
  await openFreshConversation(page)

  // The guide: a provider agents may choose, what it is good for, and its models.
  await page.getByRole('button', { name: 'Models', exact: true }).click()
  await page.getByRole('button', { name: /Add a provider/ }).click()
  await page.getByLabel('Name').fill('Strong')
  await page.getByLabel('Address').fill(`${MODEL_URL}/v1`)
  await page.getByLabel('What it is good for').fill('Strongest; for hard reviews.')
  await expect(page.getByText('28 / 300')).toBeVisible()
  await expect(page.getByLabel('Never run a model that is not on this list')).toBeDisabled()
  await page.getByRole('button', { name: 'Add a model' }).click()
  await page.getByLabel('New model’s name').fill('fake-qwen')
  await page.getByLabel('New model’s name').press('Enter')
  // Agents may use a new provider's model once the user says so (slice 81a: said of each model).
  const use = page.getByRole('switch', { name: 'Agents may use fake-qwen' })
  await expect(use).not.toBeChecked()
  await use.check()
  await page.getByRole('button', { name: 'What is known of fake-qwen' }).click()
  await page.getByLabel('Note of fake-qwen').fill('the big one')
  await page.getByLabel('Never run a model that is not on this list').check()
  await page.getByRole('button', { name: 'Add provider' }).click()

  // It was saved as it was written.
  await page.getByRole('button', { name: /^Strong/ }).click()
  await expect(page.getByRole('switch', { name: 'Agents may use fake-qwen' })).toBeChecked()
  await page.getByRole('tab', { name: 'Connection' }).click()
  await expect(page.getByLabel('What it is good for')).toHaveValue('Strongest; for hard reviews.')
  await expect(page.getByLabel('Never run a model that is not on this list')).toBeChecked()
  await page.keyboard.press('Escape')

  // The lead reads the guide in spawn_agent and picks the provider for a hard job.
  await page.getByRole('button', { name: 'Canvas', exact: true }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await ask(page, 'a hard job: look at the greeting')
  // A Reviewer changes nothing, so its own model would not be asked about: this is.
  await expect(chat.getByText('Open this sub-agent?')).toBeVisible()
  await expect(chat.getByText('Strong · fake-qwen')).toBeVisible()
  await expect(chat.getByText('chosen by Orchestrator')).toBeVisible()
  // and why, in the Lead's own words
  await expect(chat.getByText('A hard review: the note says Strong is for those.')).toBeVisible()
  await expect(chat.getByText('Looks fine.')).toHaveCount(0)

  await chat.getByRole('button', { name: 'Open agent' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await chat.getByRole('button', { name: /Reviewer.*Review hello.py/ }).click()
  // (its model and provider, and who chose them: under its window's Details)
  const own = await windowFromPanel(page)
  await openAgentFold(own, 'Details')
  await expect(own.getByText('Provider').locator('xpath=following-sibling::dd[1]')).toHaveText('Strong')
  await expect(own.getByText('Model', { exact: true }).locator('xpath=following-sibling::dd[1]')).toContainText(
    'chosen by Orchestrator: “A hard review: the note says Strong is for those.”',
  )
  await own.getByRole('button', { name: 'Close agent window' }).click()

  // put the list back so later runs start from the defaults
  await page.getByRole('button', { name: 'Models', exact: true }).click()
  await page.getByRole('button', { name: /^Strong/ }).click()
  await page.getByRole('tab', { name: 'Connection' }).click()
  await page.getByRole('button', { name: 'Delete provider' }).click()
  await expect(page.getByRole('button', { name: /^Strong/ })).toHaveCount(0)
})
