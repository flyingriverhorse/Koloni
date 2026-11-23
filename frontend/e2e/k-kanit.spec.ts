// Kanıtlı bitiş (S1): after a turn that changed code KOLONİ runs the project's tests once and says under the answer what
// was checked. The backend is shared with the other specs: what is set and written here is put back.
import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, level, openFreshConversation, setProject } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const CHECK = `python -c "print('3 passed')"`
// Checked shows once the turn is over, its checks too: a turn you watch waits at most 2 minutes for its tests, another
// of KOLONİ's runs before them too (`END_WAIT_SECONDS`). Waited for itself - not the step that wrote the file, whose
// words fold into the turn's steps as it goes on (on a loaded runner they were never seen in 20 s).
const ENDS = 135_000

test.afterEach(async ({ page }) => {
  rmSync(path.join(PROJECT_DIR, 'kanit.py'), { force: true })
  await setProject(page, { check_command: '', after_change: 'nothing' })
})

for (const theme of ['light', 'dark'] as const)
  test(`Checked under the answer after a code change (${theme})`, async ({ page }) => {
    test.setTimeout(ENDS + 45_000)
    await page.addInitScript(given => localStorage.setItem('koloni-theme', given), theme)
    await openFreshConversation(page)
    await setProject(page, { check_command: CHECK, after_change: 'check' })
    await level(page, 'auto_edit') // (the write is applied; the user's own command runs unasked)
    await page.getByLabel('Message').fill('write the checked file, k-kanit')
    await page.getByRole('button', { name: 'Send' }).click()
    const checked = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'Checked' })
    await expect(checked).toContainText(`Tests passed: ${CHECK} - 3 passed`, { timeout: ENDS })
    await expect(checked.locator('[data-state="passed"]')).toHaveCount(1)
    expect((await checked.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
