import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, dropKnowledge, e2eProject, openFreshConversation, shot } from './helpers'

// K-bilgi part 1: the project's Knowledge page from the rail - a card for each knowledge, the ready experts' (every project's)
// too, a card opened to its tabs, and "+ Add knowledge" in one window that adds to this project. What a spec makes it takes away.
test.afterEach(async ({ request }) => {
  await dropKnowledge(request, 'Tomli')
  await dropKnowledge(request, 'KOLONİ guide')
})

const lowContrast = async (page: Page, where: string) => (await page.locator(where).evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`the Knowledge page lists, opens a row and adds knowledge (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Knowledge', exact: true }).click()
    const mlflow = page.getByRole('article', { name: 'MLflow' })
    await expect(mlflow).toContainText('every project')
    await expect(mlflow).toContainText('MLflow expert · full')
    await mlflow.getByRole('button', { name: /MLflow/ }).click()
    await expect(mlflow.getByRole('tablist', { name: 'MLflow' })).toBeVisible()
    await mlflow.getByRole('button', { name: 'Try it' }).click()
    await expect(page.getByLabel(/Try it/)).toBeVisible()
    await shot(page, `k-bilgi-page-${theme}`)
    expect(await lowContrast(page, '.knowledge-page')).toEqual([])

    await page.getByRole('button', { name: '+ Add knowledge' }).click()
    const added = page.getByRole('dialog', { name: 'Add knowledge' })
    await added.getByRole('radio', { name: /Files here/ }).click()
    await added.getByLabel('Folder or file').fill('docs/')
    await added.getByLabel('Topic', { exact: true }).fill('Tomli')
    await shot(page, `k-bilgi-add-${theme}`)
    expect(await lowContrast(page, '.knowledge-add')).toEqual([])
    await added.getByRole('button', { name: 'Add without learning' }).click()
    await expect(page.getByRole('article', { name: 'Tomli' })).toContainText('not learned')
    // This project's, not every project's.
    const pid = await e2eProject(page)
    const listed = (await (await page.request.get(`/api/projects/${pid}/knowledge`, { headers: OWN })).json()) as { project_id: string | null; knowledge: { topic: string } }[]
    expect(listed.find(one => one.knowledge.topic === 'Tomli')?.project_id).toBe(pid)
  })
}

// KOLONİ's own guide: one click adds it - its source names only KOLONİ's docs/ - and nothing is learned until Learn, which
// asks for a model as any knowledge's does (it costs model calls).
test('KOLONİ’s own guide is added in one click and learns only on Learn', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  await page.getByRole('button', { name: 'Knowledge', exact: true }).click()
  await page.getByRole('button', { name: 'Add KOLONİ’s own guide' }).click()
  const guide = page.getByRole('article', { name: 'KOLONİ guide' })
  await expect(guide).toContainText('not learned')
  await expect(page.getByRole('button', { name: 'Add KOLONİ’s own guide' })).toHaveCount(0)
  const pid = await e2eProject(page)
  const listed = (await (await page.request.get(`/api/projects/${pid}/knowledge`)).json()) as { knowledge: { topic: string; sources: string[] }; state: { learning: boolean; learned: unknown } }[]
  const kept = listed.find(one => one.knowledge.topic === 'KOLONİ guide')!
  expect(kept.knowledge.sources).toEqual(['koloni-guide:'])
  expect(kept.state.learning).toBe(false)
  expect(kept.state.learned).toBeNull()
  // No role uses it and it names no model: Learn says to choose one, and nothing starts.
  await guide.getByRole('button', { name: 'Learn', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('choose a model')
  await expect(guide).toContainText('not learned')
})
