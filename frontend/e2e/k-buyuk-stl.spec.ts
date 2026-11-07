// B-341 (live): a 48.8 MB STL (977k triangles) was parsed in the worker, but putting it on the page held the
// main thread 1.9 s at once. Its pieces now go to the GPU a frame each. The longest task is measured here and
// printed; what it is held to is loose - headless Chromium draws in software (SwiftShader), not as a GPU does.
import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const BIG = path.join(PROJECT_DIR, 'big341.stl')
const TRIANGLES = 977_000

/** A binary STL of TRIANGLES small triangles in a row: an 80-byte header, the count, 50 bytes each. */
function bigStl() {
  const data = Buffer.alloc(84 + 50 * TRIANGLES)
  data.writeUInt32LE(TRIANGLES, 80)
  for (let n = 0; n < TRIANGLES; n++) {
    const at = 84 + 50 * n + 12
    const x = n % 1000
    const y = Math.floor(n / 1000)
    for (const [corner, [dx, dy]] of [[0, [0, 0]], [1, [1, 0]], [2, [0, 1]]] as const) {
      data.writeFloatLE(x + dx, at + 12 * corner)
      data.writeFloatLE(y + dy, at + 12 * corner + 4)
      data.writeFloatLE((x * y) % 7, at + 12 * corner + 8)
    }
  }
  return data
}

// (Its 2 minutes from its start on: set in the test, they did not reach the setting up of its page, which under load went
// past the 30 s of other tests.)
test.describe.configure({ timeout: 120_000 })

test.beforeAll(() => writeFileSync(BIG, bigStl()))
test.afterAll(() => rmSync(BIG, { force: true }))

test('a 48.8 MB STL is drawn without holding the page for long at once', async ({ page }) => {
  await page.addInitScript(() => {
    ;(window as unknown as { longest: number }).longest = 0
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        const w = window as unknown as { longest: number }
        w.longest = Math.max(w.longest, entry.duration)
      }
    }).observe({ type: 'longtask', buffered: true })
  })
  await openFreshConversation(page)
  // (what came before the model - the page's own start - is not its)
  await page.evaluate(() => ((window as unknown as { longest: number }).longest = 0))
  await page.getByLabel('Message').fill('show the big stl')
  await page.getByRole('button', { name: 'Send' }).click()
  const figure = page.locator('.view-panel').getByRole('figure', { name: 'big341.stl' })
  await expect(figure.locator('figcaption')).toHaveText(/977,000 triangles$/, { timeout: 60_000 })
  // (its pieces, a frame each, all shown)
  await page.waitForTimeout(3000)
  const longest = await page.evaluate(() => (window as unknown as { longest: number }).longest)
  console.log(`B-341: the longest task while the 48.8 MB STL was put on the page: ${Math.round(longest)} ms`)
  expect(longest).toBeLessThan(5000)
})
