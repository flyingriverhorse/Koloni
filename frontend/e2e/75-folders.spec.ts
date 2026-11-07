import { expect, test } from './fixtures'
import { appSettings, contrasts, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// (Slice 86b: the folders of every project and of this project went into each chat's own, "Also in this chat" in the
// folder button's panel.)
for (const theme of ['light', 'dark'] as const) {
  test(`The app › Your data says the places never opened, with why (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    // (The same in every project: The app's.)
    const settings = await appSettings(page, 'Your data')

    // The places never opened are shown with why.
    await settings.getByText(/places no agent ever opens/).click()
    const never = settings.getByRole('list', { name: 'Always blocked' })
    await expect(never.getByRole('listitem').filter({ hasText: '.ssh' }).first()).toContainText("it holds the user's settings and secrets")
    await expect(settings.getByText('In every project')).toHaveCount(0)

    const pieces = await settings.evaluate(contrasts)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `75-folders-${theme}`)
  })
}

// R56: in a window 992px wide the "51 places…" line ran past the page. It wraps.
test('the line of the places never opened wraps inside the page at 992px', async ({ page }) => {
  await page.setViewportSize({ width: 992, height: 800 })
  await openFreshConversation(page)
  const settings = await appSettings(page, 'Your data')
  const line = settings.getByText(/places no agent ever opens/)
  const [said, editor] = [await line.boundingBox(), await settings.boundingBox()]
  expect(said!.x + said!.width).toBeLessThanOrEqual(editor!.x + editor!.width)
  expect(await settings.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
})
