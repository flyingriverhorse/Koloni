import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 64: the model server on this machine, started and stopped from Local's Server tab. It is the stand-in
// (tests/fake_llama_server.py) start-backend.mjs set up, on a port of its own; no nvidia-smi is read.

test.afterEach(async ({ request }) => {
  await request.post('/api/local-server/stop', { headers: OWN })
})

for (const theme of ['light', 'dark'] as const) {
  test(`Start shows the model and its window, the output is there, Stop ends it (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await rail(page, 'Models').click()
    await page.getByRole('button', { name: /^Local/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Local' })
    await dialog.getByRole('tab', { name: 'Server' }).click()
    const panel = dialog.getByRole('tabpanel', { name: 'Server' })
    const state = panel.getByRole('status')
    await expect(state).toHaveText(/Stopped/)
    const model = panel.getByLabel('Model')
    await expect(model).toHaveValue(/e2e-model\.gguf$/)
    await expect(model.getByRole('option')).toHaveText(['None (-m not given)', /e2e-model\.gguf$/, /e2e-other\.gguf$/])
    await expect(panel.getByLabel('Context (-c)')).toHaveValue('8192')

    await panel.getByRole('button', { name: 'Start' }).click()
    await expect(state).toHaveText(/Running · e2e-model\.gguf · n_ctx 8,192/, { timeout: 15_000 })
    await expect(panel.getByText('GPU –')).toBeVisible()
    await panel.locator('summary', { hasText: 'Server output' }).click()
    const output = panel.getByLabel('Server output')
    await expect(output).toContainText('server is listening')
    await expect(output).not.toContainText('sk-fake')
    await shot(page, `64-local-server-${theme}`)
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    await panel.getByRole('button', { name: 'Stop' }).click()
    await expect(state).toHaveText(/Stopped/)
    await expect(panel.getByRole('button', { name: 'Start' })).toBeVisible()
  })
}
