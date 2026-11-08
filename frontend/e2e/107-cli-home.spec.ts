// K-ev-klasoru: a file in a CLI's own folder in the home folder is read on a card that says it is that CLI's settings
// for the whole computer - once, with no folder to allow. Run with a home folder of its own (KOLONI_E2E_HOME): the
// backend is given it, and this machine's own ~/.codex is never looked at.
import { mkdirSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, settled } from './helpers'

const HOME = process.env.KOLONI_E2E_HOME
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'ev-shots')

test("a read of Codex's settings is asked for on its own card, in light and dark", async ({ page }) => {
  test.skip(!HOME, 'needs a home folder of its own: KOLONI_E2E_HOME')
  const config = path.join(HOME!, '.codex', 'config.toml')
  mkdirSync(path.dirname(config), { recursive: true })
  writeFileSync(config, 'model = "e2e-model"\n')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const card = chat.locator('.cmd-approval').filter({ hasText: 'Read this computer’s settings?' })

  await page.getByLabel('Message').fill('read the codex settings')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Read this computer’s settings?')).toBeVisible()
  await expect(chat.getByText(`Orchestrator wants to read ${config}`)).toBeVisible()
  await expect(chat.getByText(/This folder is Codex's settings for this whole computer: changing it affects every project/)).toBeVisible()
  await expect(chat.getByRole('button', { name: /this folder/ })).toHaveCount(0)
  mkdirSync(SHOTS, { recursive: true })
  await settled(page)
  await card.screenshot({ path: path.join(SHOTS, 'cli-home-card-light.png') })

  await page.evaluate(() => localStorage.setItem('koloni-theme', 'dark'))
  await page.reload()
  await expect(chat.getByText('Read this computer’s settings?')).toBeVisible()
  await settled(page)
  await card.screenshot({ path: path.join(SHOTS, 'cli-home-card-dark.png') })
  await page.evaluate(() => localStorage.removeItem('koloni-theme'))

  await chat.getByRole('button', { name: 'Allow once' }).click()
  await expect(chat.getByText('Codex is set to e2e-model.')).toBeVisible()
  await expect(chat.getByRole('button', { name: 'Allow once' })).toHaveCount(0)
})
