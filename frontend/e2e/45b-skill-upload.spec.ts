import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, rail } from './helpers'
import { SKILL_DIR } from './paths.mjs'

test('a skill is uploaded from a folder chosen in the browser, shown on the card, and added', async ({ page }) => {
  // A folder of another computer's, as the browser's folder picker hands it over.
  const folder = path.join(SKILL_DIR, 'upload', 'brief')
  rmSync(folder, { recursive: true, force: true })
  for (const [rel, content] of Object.entries({
    'SKILL.md': '---\nname: brief\ndescription: Say less.\n---\nOne line is enough.\n',
    'scripts/count.py': "print('counted')\n",
    '.env': 'TOKEN=abc\n',
  })) {
    mkdirSync(path.dirname(path.join(folder, rel)), { recursive: true })
    writeFileSync(path.join(folder, rel), content)
  }
  await openFreshConversation(page)
  // K-skill-uyum: added on the Tools page's SKILLS, KOLONİ's store.
  await rail(page, 'Tools').click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: /^A skill/ }).click()
  const skills = page.getByRole('tabpanel', { name: /^Skills/ })

  const chooser = page.waitForEvent('filechooser')
  await skills.getByRole('button', { name: 'Choose folder…' }).click()
  await (await chooser).setFiles(folder)
  await expect(skills.getByText('Its scripts: scripts/count.py')).toBeVisible()
  await expect(skills.getByText('Not copied:')).toContainText('.env')
  await skills.getByText('Show scripts/count.py').click()
  await expect(skills.getByText("print('counted')")).toBeVisible()
  await skills.getByRole('button', { name: 'Add skill' }).click()
  const card = skills.getByRole('listitem').filter({ hasText: 'Say less.' })
  await expect(card.getByRole('switch', { name: 'brief on' })).toBeChecked()
  await card.getByRole('button', { name: /^brief/ }).click()
  await expect(card.getByText(/from uploaded \(brief\)/)).toBeVisible()
})
