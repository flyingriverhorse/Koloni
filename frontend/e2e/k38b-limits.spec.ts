// K-38b-sinirlar in the browser: on a narrow canvas an agent's window opens clear of the chat, beside the
// Workspace window without hiding it, and says on its header what came new while the user looked elsewhere.
import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test, type Locator, type Page } from './fixtures'
import { contrasts, openFreshConversation } from './helpers'

// Kept for the slice's report, outside the repo (as ac-room-window's are).
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'cv-shots')
const keep = async (page: Page, name: string) => {
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

type Box = { x: number; y: number; width: number; height: number }
const box = async (target: Locator) => (await target.boundingBox())!
const meets = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
const holds = (a: Box, b: Box) => a.x <= b.x && a.y <= b.y && a.x + a.width >= b.x + b.width && a.y + a.height >= b.y + b.height

for (const [width, height] of [
  [1024, 720],
  [1440, 900],
] as const) {
  for (const theme of ['light', 'dark'] as const) {
    test(`K-38b-sinirlar ${width}x${height} (${theme}): an agent's window opens off the chat, not over Workspace, and counts what came new`, async ({ page }) => {
      await page.setViewportSize({ width, height })
      await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
      await openFreshConversation(page)
      const chat = page.getByRole('region', { name: 'Chat' })
      await page.getByLabel('Message').fill('run the tests')
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(chat.getByText('Run this command?')).toBeVisible()

      // Workspace beside the chat, then the Lead picked (the inspector takes the stage's right) and its window opened.
      await chat.getByRole('button', { name: /^Workspace/ }).click()
      const files = page.getByRole('region', { name: 'Workspace' })
      await expect(files).toBeVisible()
      const lead = page.locator('.react-flow__node-agent', { hasText: 'Orchestrator' })
      await lead.locator('.node-title').click()
      await expect(page.getByRole('complementary', { name: 'Inspector' })).toBeVisible()
      await lead.locator('.node-title').dblclick()
      const window = page.getByRole('region', { name: 'Agent window' })
      await expect(window).toBeVisible()

      const [stage, own, under, other] = [await box(page.locator('.stage')), await box(window), await box(chat), await box(files)]
      expect(meets(own, under)).toBe(false)
      expect(holds(own, other) || holds(other, own)).toBe(false)
      expect(own.x >= stage.x && own.y >= stage.y && own.x + own.width <= stage.x + stage.width && own.y + own.height <= stage.y + stage.height).toBe(true)
      await keep(page, `k38b-${width}-${theme}-opened`)

      // Looking at the chat, the user lets the command run: the Lead's answer is one step more, said on the window's header.
      await chat.getByLabel('Message').click()
      await chat.getByRole('button', { name: 'Run once' }).click()
      await expect(chat.getByText('The tests pass.')).toBeVisible()
      const fresh = window.locator('.changes-bar').getByText(/^\d+ new$/)
      await expect(fresh).toHaveText('1 new')
      expect((await fresh.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      await keep(page, `k38b-${width}-${theme}-new`)

      // Back on its window, it is seen.
      await window.locator('.agent-feed').click()
      await expect(fresh).toHaveCount(0)
    })
  }
}
