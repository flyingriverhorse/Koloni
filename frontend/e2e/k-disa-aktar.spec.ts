// K-disa-aktar: Your data, in Settings › The app (tek-ev) - everything exported to one .zip, and that .zip staged to be restored at the
// next start. The run never restarts: the stage is cancelled at the end, and the e2e's runtime folder is cleared each run.
import { mkdirSync, readFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { appSettings, contrasts, LINK, OWN } from './helpers'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'da-shots')

// The backend is shared with the specs after this one: whatever happens here, nothing is left held.
test.afterEach(async ({ page }) => {
  expect((await page.request.post('/api/hold/resume', { headers: OWN })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme Export everything downloads a .zip, and restoring it says it is restored at the next start`, async ({
    page,
  }) => {
    await page.addInitScript(given => localStorage.setItem('koloni-theme', given), theme)
    await page.goto(LINK)
    await appSettings(page, 'Your data')
    const panel = page.getByRole('region', { name: 'Your data' })
    await expect(
      panel.getByRole('checkbox', { name: 'Include API keys and secrets (keep this file safe)' }),
    ).not.toBeChecked()
    mkdirSync(SHOTS, { recursive: true })
    await panel.screenshot({ path: path.join(SHOTS, `your-data-${theme}.png`) })

    // Fetched with the key in its header and saved from the page: no address with the key in the browser's list of downloads.
    const downloading = page.waitForEvent('download')
    await panel.getByRole('button', { name: 'Export everything' }).click()
    const download = await downloading
    expect(download.url()).toMatch(/^blob:/)
    expect(download.suggestedFilename()).toMatch(/^koloni-\d{4}-\d{2}-\d{2}\.zip$/)
    const file = path.join(test.info().outputDir, download.suggestedFilename())
    await download.saveAs(file)
    expect(readFileSync(file).subarray(0, 2).toString()).toBe('PK') // a .zip
    await expect(panel).toBeVisible() // (the app stayed where it was)

    // A restore is refused while any turn runs, or a working copy is kept: what a spec before this one left (a card
    // that waits, k-away-dal's kept copy) is stopped as Stop everything stops it - waited for: Stop waits 10 s at most
    // - and discarded as Settings › Your data's Discard does.
    expect((await page.request.post('/api/hold', { headers: OWN })).ok()).toBe(true)
    await expect
      .poll(async () => (await (await page.request.get('/api/hold')).json()).running, { timeout: 15_000 })
      .toBe(0)
    for (const one of (await (await page.request.get('/api/storage')).json()).kept as { merge_id: string }[])
      expect((await page.request.post(`/api/merges/${one.merge_id}/reject`, { headers: OWN })).ok()).toBe(true)
    await panel.getByLabel('An export to restore').setInputFiles(file)
    const said = panel.getByRole('status')
    await expect(said).toContainText(
      'Ready to restore. It replaces your data the next time KOLONİ starts: close KOLONİ and start it again. Until then nothing changes, and anything you do meanwhile is set aside with your current data in runtime/before-restore/.',
    )
    await expect(said).toContainText('What starts by itself waits until you press Resume.')
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await panel.screenshot({ path: path.join(SHOTS, `restore-staged-${theme}.png`) })
    await said.getByRole('button', { name: 'Cancel' }).click()
    await expect(said).toHaveCount(0)
  })
