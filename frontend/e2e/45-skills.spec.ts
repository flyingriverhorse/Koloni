import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { editRole, openFreshConversation, rail } from './helpers'
import { SKILL_DIR } from './paths.mjs'

/** A skill's folder of the user's, made afresh. */
function skillFolder(name: string, files: Record<string, string>) {
  const folder = path.join(SKILL_DIR, name)
  rmSync(folder, { recursive: true, force: true })
  for (const [rel, content] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(folder, rel)), { recursive: true })
    writeFileSync(path.join(folder, rel), content)
  }
  return folder
}

test('a skill is added on the Tools page and given to a role on its row there, and the Lead proposes another on a card', async ({ page }) => {
  const tidy = skillFolder('tidy', {
    'SKILL.md': '---\nname: tidy\ndescription: Keep changes small.\nallowed-tools: Read, Grep\n---\nWrite the least code that works.\n',
    'scripts/check.py': "print('ok')\n",
    LICENSE: 'MIT License\n\nCopyright (c) someone\n',
    '.env': 'TOKEN=abc\n',
  })
  skillFolder('plain', { 'SKILL.md': '---\nname: plain\ndescription: Say it plainly.\n---\nShort words.\n' })
  await openFreshConversation(page)

  // 0.1.0-ui: the role's servers and skills say "on Tools →"; the Tools page's Skills tab is where the store is.
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Coder', 'Tools')
  await page.getByRole('button', { name: 'on Tools →' }).click()
  await page.getByRole('tab', { name: /^Skills/ }).click()
  const skills = page.getByRole('tabpanel', { name: /^Skills/ })
  await expect(skills).toBeVisible()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: /^A skill/ }).click()
  // The folder is read, and its licence and scripts are shown before it is kept.
  await skills.getByLabel('Skill folder').fill(tidy)
  await skills.getByRole('button', { name: 'Read the folder' }).click()
  await expect(skills.getByText('MIT License').first()).toBeVisible()
  await expect(skills.getByText('Its scripts:').first()).toContainText('scripts/check.py')
  // slice 92: what it declares it may use is said, and that KOLONİ gives it none of that
  await expect(skills.getByText(/^It declares allowed-tools:/)).toContainText('Read, Grep. KOLONİ gives a skill none of them')
  await expect(skills.getByLabel('Run the scripts of tidy without asking')).toBeChecked()
  // what is not copied is said, and each script can be read before the yes
  await expect(skills.getByText('Not copied:')).toContainText('.env')
  await skills.getByText('Show scripts/check.py').click()
  await expect(skills.getByText("print('ok')")).toBeVisible()
  await skills.getByRole('button', { name: 'Add skill' }).click()
  // Kept: its row, given to no role yet; unfolded, its SKILL.md beside its files - the .env was not copied.
  const card = skills.getByRole('listitem').filter({ hasText: 'Keep changes small.' })
  const row = card.getByRole('button', { name: /^tidy/ })
  await expect(row).toContainText('no role')
  await row.click()
  await card.getByText('Show SKILL.md').click()
  await expect(card.getByText(/Write the least code that works\./)).toBeVisible()
  await expect(card.getByText('LICENSE, SKILL.md, scripts/check.py')).toBeVisible()

  // The Coder is given it on its row, saved at once; the row says what it asks for, and the role lists it.
  const win = card.getByRole('group', { name: 'Skill tidy' })
  await expect(win.getByText('read files', { exact: true })).toBeVisible()
  await win.getByRole('checkbox', { name: /Coder/ }).click()
  await expect(win.getByRole('checkbox', { name: /Coder/ })).toBeChecked()
  await expect(row).toContainText('Coder')
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Coder', 'Tools')
  await expect(page.getByRole('complementary', { name: 'Role Coder' }).getByRole('button', { name: 'tidy, on the Tools page' })).toBeVisible()

  // The Lead proposes one: a card with what it holds, and nothing is kept before the yes.
  await rail(page, 'Canvas').click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('add the plain skill')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Add this skill?')).toBeVisible()
  await expect(chat.getByText('licence unknown')).toBeVisible()
  await expect(chat.getByText(/Given to: Coder\./)).toBeVisible()
  await expect(chat.getByText('It has no scripts.')).toBeVisible()
  await chat.getByRole('button', { name: 'Add skill' }).click()
  await expect(chat.getByText('The skill is added.')).toBeVisible()
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Coder', 'Tools')
  await expect(page.getByRole('complementary', { name: 'Role Coder' }).getByRole('button', { name: 'plain, on the Tools page' })).toBeVisible()
})
