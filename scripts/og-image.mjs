// Renders scripts/og-image.html to pages/assets/og.jpg (1200x630), the landing page's share card.
// Run from the repo root: node scripts/og-image.mjs   (uses the frontend's Playwright and its Chromium)
import { fileURLToPath } from 'node:url'
import { statSync } from 'node:fs'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const html = new URL('./og-image.html', import.meta.url)
const out = fileURLToPath(new URL('../pages/assets/og.jpg', import.meta.url))

const browser = await chromium.launch()
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 })
  // only the repo's own files: no fonts or pictures from the network
  const blocked = []
  await page.route('**/*', (route) => {
    if (route.request().url().startsWith('file:')) return route.continue()
    blocked.push(route.request().url())
    return route.abort()
  })
  await page.goto(html.href, { waitUntil: 'load' })
  // a broken font path would silently fall back to Georgia / system-ui
  const missing = await page.evaluate(async () => {
    await document.fonts.ready
    return [...document.fonts].filter((f) => f.status !== 'loaded').map((f) => `${f.family} ${f.style} ${f.unicodeRange}`)
  })
  if (missing.length || blocked.length) throw new Error(`fonts not loaded: ${missing.join('; ')} | blocked: ${blocked.join(' ')}`)
  await page.screenshot({ path: out, type: 'jpeg', quality: 85, clip: { x: 0, y: 0, width: 1200, height: 630 } })
} finally {
  await browser.close()
}
console.log(`${out}: ${Math.round(statSync(out).size / 1024)} KB`)
