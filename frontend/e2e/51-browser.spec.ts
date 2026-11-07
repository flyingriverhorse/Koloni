import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// Slice 51: the agent tries a page itself. The backend's browser is the stand-in (start-backend.mjs sets
// KOLONI_BROWSER_FAKE): it fetches the page for real, so what the Lead reads is the page's own text.
const PAGE = path.join(PROJECT_DIR, 'page51.html')

test.afterEach(() => rmSync(PAGE, { force: true }))

test('the agent opens a page of the project in its browser; its screenshot is under the step and beside the chat', async ({ page }) => {
  writeFileSync(
    PAGE,
    '<!doctype html><html><head><meta charset="utf-8"><title>Page 51</title></head><body><h1>Hello from 51</h1><button>Start</button></body></html>',
  )
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('try the page, 51')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The page says Hello from 51.')).toBeVisible({ timeout: 30_000 })
  // The three calls are one run, closed, and nothing was asked; opened, each reads in words.
  await expect(page.locator('[data-run="waiting_approval"]')).toHaveCount(0)
  await chat.getByRole('button', { name: 'Tried the page in 3 steps, 3 calls, done' }).click()
  const rows = chat.locator('.tool-run .tool-row')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText('opened page51.html')
  await expect(rows.nth(1)).toContainText('took a screenshot')
  await expect(rows.nth(2)).toContainText('read the page')
  // The screenshot: a small picture under its step, served as a PNG under the call's own id.
  const picture = chat.getByRole('img', { name: /^Screenshot .+\.png$/ })
  await expect(picture).toBeVisible()
  const src = (await picture.getAttribute('src'))!
  expect(src).toMatch(/^\/api\/conversations\/[0-9a-f]{32}\/views\/[0-9a-f]{32}\/[\w-]+\.png$/)
  const served = await page.request.get(src)
  expect(served.ok()).toBe(true)
  expect(served.headers()['content-type']).toBe('image/png')
  // And beside the chat: the Workspace window opened by itself at the newest screenshot (the live view).
  const files = page.locator('#files-window')
  await expect(files).toBeVisible()
  await expect(files.locator('img.view-image')).toBeVisible()
  await shot(page, '51-browser-step-and-view')
})
