// K-buyuk-proje, first slice, in the browser: Project settings → Project map lists the folder's parts found by their
// files, with a guessed test command; a test command typed in place is saved with Enter and stays after Refresh.
// Both themes read at 4.5. The parts are made for this spec and removed again, with the command it saved.
import { rmSync, writeFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { type APIRequestContext, expect, test } from './fixtures'
import { contrasts, OWN, openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const PARTS = ['map-core', 'map-web']

test.beforeEach(() => {
  mkdirSync(path.join(PROJECT_DIR, 'map-core', 'tests'), { recursive: true })
  writeFileSync(path.join(PROJECT_DIR, 'map-core', 'pyproject.toml'), "[project]\nname = 'core'\n")
  writeFileSync(path.join(PROJECT_DIR, 'map-core', 'tests', 'test_a.py'), '')
  mkdirSync(path.join(PROJECT_DIR, 'map-web'), { recursive: true })
  writeFileSync(path.join(PROJECT_DIR, 'map-web', 'package.json'), '{"name": "web"}')
})

// The backend is shared with the other specs: what this one adds goes, failed or not.
test.afterEach(async ({ request }: { request: APIRequestContext }) => {
  // (This spec's project by its folder: the backend may hold others.)
  const same = (one: string) => path.resolve(one).toLowerCase() === path.resolve(PROJECT_DIR).toLowerCase()
  const projects: { id: string; root_path: string }[] = await (await request.get('/api/projects')).json()
  const project = projects.find(one => same(one.root_path))
  if (project) await request.delete(`/api/projects/${project.id}/map/test?path=map-web%2F`, { headers: OWN })
  for (const part of PARTS) rmSync(path.join(PROJECT_DIR, part), { recursive: true, force: true })
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: the parts are listed and a test command is saved in place`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const settings = page.getByRole('form', { name: 'Project settings' })
    await settings.getByRole('button', { name: /^This folder/ }).click()
    // (Made fresh: an earlier spec's look at the folder may be kept.)
    await settings.getByRole('button', { name: 'Refresh' }).click()
    await expect(settings.getByRole('status')).toHaveText('Refreshed')
    const table = settings.getByRole('table', { name: 'Parts of this folder' })
    const core = table.getByRole('row').filter({ hasText: 'map-core/' })
    await expect(core).toContainText('Python')
    await expect(core.getByLabel('Test command for map-core/')).toHaveValue(/pytest$/)
    const web = core.page().getByLabel('Test command for map-web/')
    await expect(web).toHaveValue('')
    await web.fill('npm run check')
    await web.press('Enter')
    await expect(settings.getByRole('status')).toHaveText('Saved')
    await settings.getByRole('button', { name: 'Refresh' }).click()
    await expect(settings.getByRole('status')).toHaveText('Refreshed')
    await expect(web).toHaveValue('npm run check')
    const pieces = await settings.locator('.role-editor').evaluate(contrasts)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
  })
