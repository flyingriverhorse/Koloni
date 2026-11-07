// 89m: "Finish only when the tests pass" in the project's settings - off by itself while the tests' time is not
// known, with why under it; the backend is shared with the other specs, so what is set here is put back.
import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, contrasts, e2eProject, openFreshConversation } from './helpers'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'tm-shots')

let made = ''
async function set(request: APIRequestContext, data: object) {
  expect((await request.patch(`/api/projects/${made}`, { headers: OWN, data })).ok()).toBe(true)
}
test.afterEach(({ request }) => set(request, { check_command: '', finish_tests: null }))

for (const theme of ['light', 'dark'] as const)
  test(`the switch says why it is off by itself, and saves (${theme})`, async ({ page, request }) => {
    await page.addInitScript(given => localStorage.setItem('koloni-theme', given), theme)
    made = await e2eProject(page)
    await set(request, { check_command: 'python -m pytest -q' })  // (before the page reads the project)
    await openFreshConversation(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const settings = page.getByRole('form', { name: 'Project settings' })
    await settings.getByRole('button', { name: /^Agents/ }).click()
    const box = settings.getByRole('checkbox', { name: /^Finish only when the tests pass/ })
    await expect(box).not.toBeChecked()
    await expect(settings.getByTestId('finish-tests-why')).toHaveText(
      'By default off: test time not known yet - turn it on if your tests are quick.')
    await box.scrollIntoViewIfNeeded()
    mkdirSync(SHOTS, { recursive: true })
    await settings.screenshot({ path: path.join(SHOTS, `finish-tests-${theme}.png`) })
    expect((await settings.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    const sent = page.waitForRequest(r => r.method() === 'PATCH' && /\/api\/projects\/[^/]+$/.test(r.url()))
    await box.check()
    await settings.getByRole('button', { name: 'Save' }).click()
    expect((await sent).postDataJSON()).toEqual({ finish_tests: true })
    await expect(settings.getByTestId('finish-tests-why')).toHaveText(
      'You set this; by default it would be off: test time not known yet - turn it on if your tests are quick.')
    await expect(settings.getByRole('status')).toHaveText('Saved')
  })
