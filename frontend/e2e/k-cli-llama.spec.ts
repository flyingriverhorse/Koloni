import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, openFreshConversation } from './helpers'
import { FAKE_CLAUDE, MODEL_URL } from './paths.mjs'

const NAME = 'Claude local'

/** The stand-in provider is taken off the list, however many of it there are. */
async function remove(request: APIRequestContext) {
  const listed: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const provider of listed.filter(p => p.name === NAME)) {
    await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  }
}

// K-cli-llama: Claude Code on a model server of the user's (the stand-in model server here), checked against it.
test.describe('Claude Code on a model server of your own', () => {
  test.beforeEach(async ({ request }) => remove(request))
  test.afterEach(async ({ request }) => remove(request))

  test('its Check asks that server, and one that does not answer is refused', async ({ page }) => {
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill(NAME)
    await page.getByLabel('Kind').selectOption({ label: 'Claude Code (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_CLAUDE)
    await page.getByText('Use a model server of your own instead (optional)').click()
    await page.getByLabel('Model server address').fill(`${MODEL_URL}/v1`)
    await page.getByRole('button', { name: 'Add provider' }).click()
    await page.getByRole('button', { name: new RegExp(`^${NAME}`) }).click()
    await page.getByRole('tab', { name: 'Connection' }).click()
    await expect(page.getByLabel('Model server address')).toHaveValue(`${MODEL_URL}/v1`)
    await page.getByRole('button', { name: 'Test', exact: true }).click()
    await expect(page.getByText('The claude command was found, and your model server answered.')).toBeVisible()

    // Nothing listens on port 9 here: the run would be refused before the CLI starts.
    await page.getByLabel('Model server address').fill('http://127.0.0.1:9/v1')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: 'Test', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('start your local model server first')
  })
})
