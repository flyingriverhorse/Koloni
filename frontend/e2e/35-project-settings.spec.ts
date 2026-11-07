import { expect, test, type APIRequestContext, type Page } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const SECTIONS = ['Agents', 'Asking and away', 'New chats start with', 'Limits and money', 'Commands and secrets', 'Runs without asking', 'Checks and git', 'Memory and web', 'Notifications', 'This folder']

// What this spec changes starts and ends as a fresh project has it: the backend is shared with the other specs.
async function putBack({ request }: { request: APIRequestContext }) {
  const [project] = await (await request.get('/api/projects')).json()
  if (project) await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { auto_notes: false, turn_token_limit: null, hide_secrets: true } })
}
test.beforeEach(putBack)
test.afterEach(putBack)

/** Where the canvas is and how near: React Flow's own transform of it. */
const viewport = (page: Page) => page.locator('.react-flow__viewport').evaluate(el => (el as HTMLElement).style.transform)

/** Waits until the canvas has stopped moving. */
async function settled(page: Page) {
  let last = ''
  await expect
    .poll(
      async () => {
        const [was, now] = [last, await viewport(page)]
        last = now
        return was === now
      },
      { intervals: [300] },
    )
    .toBe(true)
}

test('the canvas under the settings: new work that came meanwhile is in view when they close, and a selected node has not moved', async ({ page }) => {
  await openFreshConversation(page)
  const gear = page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' })
  const stage = page.locator('.react-flow')
  const agents = page.locator('.react-flow__node-agent')
  const inView = async () => {
    const around = (await stage.boundingBox())!
    const boxes = await Promise.all((await agents.all()).map(node => node.boundingBox()))
    return boxes.every(box => box && box.x >= around.x && box.y >= around.y && box.x + box.width <= around.x + around.width && box.y + box.height <= around.y + around.height)
  }

  // The lead takes a moment before it starts its two reviewers: by then the settings are open over the canvas.
  await page.getByLabel('Message').fill('have both files reviewed slowly')
  await page.getByRole('button', { name: 'Send' }).click()
  await gear.click()
  await expect(page.getByRole('form', { name: 'Project settings' })).toBeVisible()
  await expect(agents).toHaveCount(3, { timeout: 15_000 })
  await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 20_000 })
  await gear.click()
  await settled(page)
  await expect.poll(inView).toBe(true)
  // ... and fitted, as new work is on a canvas in view: the canvas's own Fit View changes nothing.
  // (Fitted against the hidden stage of no size, the turn was drawn at the smallest zoom.)
  const shown = await viewport(page)
  await page.getByRole('button', { name: 'Fit View' }).click()
  await settled(page)
  expect(await viewport(page)).toBe(shown)

  // A node selected stays where it is, while the settings are open and after.
  const lead = agents.first()
  await lead.click()
  await settled(page)
  const [before, where] = [await viewport(page), await lead.boundingBox()]
  await gear.click()
  await expect(page.getByRole('form', { name: 'Project settings' })).toBeVisible()
  await page.waitForTimeout(400) // (a move would take 200 ms)
  expect(await viewport(page)).toBe(before)
  await gear.click()
  await settled(page)
  expect(await viewport(page)).toBe(before)
  expect(await lead.boundingBox()).toEqual(where)
})

test('secret files are hidden from commands until the box is cleared, and cleared it stays so', async ({ page }) => {
  await openFreshConversation(page)
  const settings = page.getByRole('form', { name: 'Project settings' })
  const hide = settings.getByLabel(/^Hide secret files from commands/)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await settings.getByRole('button', { name: /^Commands/ }).click()
  await expect(hide).toBeChecked()
  await hide.uncheck()
  await settings.getByRole('button', { name: 'Save' }).click()
  await expect(settings.getByRole('status')).toHaveText('Saved')
  await page.reload()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await settings.getByRole('button', { name: /^Commands/ }).click()
  await expect(hide).not.toBeChecked()
})

for (const theme of ['light', 'dark'] as const) {
  test(`Settings › This project is a page of sections, opened and closed by ⚙ on the rail (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const gear = page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' })
    const settings = page.getByRole('form', { name: 'Project settings' })
    // A message being typed is still there when the page closes: the canvas was only hidden under it.
    await page.getByLabel('Message').fill('a message not sent yet')

    await gear.click()
    await expect(settings).toBeVisible()
    await expect(page.getByLabel('Message')).toBeHidden()
    for (const section of SECTIONS) {
      const row = settings.getByRole('button', { name: new RegExp(`^${section}`) })
      await row.click()
      await expect(row).toHaveAttribute('aria-current', 'true')
      await shot(page, `35-settings-${section.toLowerCase().replace(/’/g, '').replace(/ /g, '-')}-${theme}`)
    }

    // A short explanation behind ⓘ opens from its button over the page, inside the window however narrow it is; Esc closes it alone.
    await settings.getByRole('button', { name: /^Limits and money/ }).click()
    const hint = settings.locator('.hint', { hasText: /waits for a slot/ })
    const bubble = hint.locator('.hint-bubble')
    await hint.getByRole('button', { name: 'About this' }).click()
    await expect(bubble).toBeVisible()
    await shot(page, `35-settings-hint-${theme}`)
    await page.setViewportSize({ width: 420, height: 900 })
    await expect
      .poll(async () => {
        const box = (await bubble.boundingBox())!
        return box.x >= 0 && box.x + box.width <= 420
      })
      .toBe(true)
    await page.keyboard.press('Escape')
    await expect(bubble).toBeHidden()
    await expect(settings).toBeVisible()
    await expect(hint.getByRole('button', { name: 'About this' })).toBeFocused()
    await page.setViewportSize({ width: 1440, height: 900 })

    // A section's Save sends that section alone; another's change waits, marked.
    await settings.getByRole('button', { name: /^Limits and money/ }).click()
    await settings.getByLabel('Stop the work on a message over this many tokens').fill('5000')
    await settings.getByRole('button', { name: /^Memory and web/ }).click()
    await settings.getByLabel(/^Note what the work found, by itself/).check()
    const sent = page.waitForRequest(r => r.method() === 'PATCH' && /\/api\/projects\/[^/]+$/.test(r.url()))
    await settings.getByRole('button', { name: 'Save' }).click()
    expect((await sent).postDataJSON()).toEqual({ auto_notes: true })
    await expect(settings.getByRole('button', { name: /^Memory and web/ })).toHaveText('Memory and web')
    await expect(settings.getByRole('status')).toHaveText('Saved')
    await expect(settings.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await expect(settings.getByRole('button', { name: /^Limits and money/ })).toHaveText('Limits and moneynot saved')
    // (a state the row is described by, not a word of its name: "not saved" would be found as a Save button)
    await expect(settings.getByRole('button', { name: /^Limits and money/ })).toHaveAccessibleName('Limits and money')
    await expect(settings.getByRole('button', { name: /^Limits and money/ })).toHaveAccessibleDescription('not saved')
    await shot(page, `35-settings-not-saved-${theme}`)

    if (theme === 'dark') {
      // Every piece of text of the page - the list with its marks, and each section - reads at 4.5 or more.
      for (const section of SECTIONS) {
        await settings.getByRole('button', { name: new RegExp(`^${section}`) }).click()
        await settings.locator('.hint-bubble').evaluateAll(hints => hints.forEach(hint => ((hint as HTMLElement).hidden = false)))
        const pieces = await settings.evaluate(contrasts)
        expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
      }
    }

    // The keyboard goes down the list, and where it is shows.
    await settings.getByRole('button', { name: /^Agents/ }).click()
    await page.keyboard.press('Tab')
    const next = settings.getByRole('button', { name: /^Asking and away/ })
    await expect(next).toBeFocused()
    expect(await next.evaluate(row => getComputedStyle(row).outlineStyle)).toBe('solid')

    // The same ⚙ closes it, throwing away what was not saved; the message is still being typed.
    await gear.click()
    await expect(settings).toHaveCount(0)
    await expect(page.getByLabel('Message')).toHaveValue('a message not sent yet')
    await gear.click()
    await settings.getByRole('button', { name: /^Limits and money/ }).click()
    await expect(settings.getByLabel('Stop the work on a message over this many tokens')).toHaveValue('')
    // A page chosen on the rail closes it too.
    await rail(page, 'Board').click()
    await expect(settings).toHaveCount(0)
    await expect(page.getByRole('region', { name: 'Ended today' })).toBeVisible()
  })
}
