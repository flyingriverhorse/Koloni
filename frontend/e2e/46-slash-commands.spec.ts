// Slice 46 in the browser: `/` at the start of the message box opens its commands; /stop stops
// the turn at work and is off while none is; /coder hands the task to the Lead for a Coder,
// whose sub-agent is still asked for as before; the menu and the chip read at 4.5 in both themes.
import { expect, test, type Locator } from './fixtures'
import { contrasts, openFreshConversation, shot, projectSettings, saveSettings } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

async function reads(root: Locator, least: number) {
  // (Read again till the least is drawn, as 42c's: the menu's own commands and roles come with their own reads.)
  await expect
    .poll(async () => {
      const pieces = await root.evaluate(contrasts)
      return pieces.length < least ? `only ${pieces.length} of ${least} pieces drawn` : pieces.filter(piece => piece.ratio < 4.5)
    })
    .toEqual([])
}

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: the menu, /stop and /coder`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    const box = chat.getByRole('textbox', { name: 'Message' })
    const menu = chat.getByRole('listbox', { name: 'Commands' })
    // /model, /room and /mode open what their buttons open - Work together from under More, closed.
    // (Each once it is on: off till the page has read the providers, or the roles, it opens with.)
    const on = async (name: string) => {
      const option = menu.getByRole('option', { name: new RegExp(`^/${name}`) })
      await expect(option).toBeVisible()
      await expect(option).not.toHaveAttribute('aria-disabled', 'true')
    }
    await box.fill('/model')
    await on('model')
    await page.keyboard.press('Enter')
    await expect(chat.getByRole('form', { name: 'Model for this conversation' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(chat.getByRole('button', { name: 'More', exact: true })).toHaveAttribute('aria-expanded', 'false')
    await box.fill('/room')
    await on('room')
    await page.keyboard.press('Enter')
    await expect(chat.getByRole('form', { name: 'Work together' })).toBeFocused()
    await page.keyboard.press('Escape')
    await page.keyboard.press('Escape')
    await expect(chat.getByRole('button', { name: 'More', exact: true })).toHaveAttribute('aria-expanded', 'false')

    // A sub-agent waits to be let open: nothing it would write is left for the other specs.
    const settings = await projectSettings(page, /^Asking and away/)
    await settings.getByLabel('Opening a sub-agent').selectOption('always')
    await saveSettings(page)

    // in the middle of a line `/` is only written
    await box.fill('a/b')
    await expect(menu).toHaveCount(0)
    await box.fill('')
    await box.press('/')
    await expect(menu).toBeVisible()
    await expect(box).toHaveAttribute('aria-activedescendant', /.+/)
    // above the box
    expect((await menu.boundingBox())!.y + (await menu.boundingBox())!.height).toBeLessThanOrEqual((await box.boundingBox())!.y)
    await expect(menu.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
    await reads(menu, 10)
    if (process.env.KOLONI_SHOTS) await shot(page, `46-menu-${theme}`)
    // Esc is the menu's: the text stays, and so does the chat
    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)
    await expect(box).toHaveValue('/')
    await expect(chat.getByRole('tab', { name: 'Chat' })).toBeVisible()
    // the list, pressed or scrolled, and Shift+Tab leave the focus with what is typed
    await box.fill('')
    await box.press('/')
    const list = (await menu.boundingBox())!
    await page.mouse.move(list.x + list.width - 3, list.y + 3)
    await page.mouse.down()
    await page.mouse.up()
    await expect(box).toBeFocused()
    await expect(menu).toBeVisible()
    await page.keyboard.press('Shift+Tab')
    expect(await page.evaluate(() => document.activeElement === document.body || document.activeElement?.getAttribute('role') === 'listbox')).toBe(false)

    // no turn at work: /stop is off and says why
    await box.fill('/st')
    const stop = menu.getByRole('option', { name: /^\/stop/ })
    await expect(stop).toHaveAttribute('aria-disabled', 'true')
    await expect(stop).toContainText('nothing is at work')
    await box.fill('')

    // a turn waits on a command: /stop stops it
    await box.fill('run the slow job')
    await chat.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByRole('button', { name: 'Run once' })).toBeVisible({ timeout: 20_000 })
    await box.fill('/sto')
    await expect(stop).not.toHaveAttribute('aria-disabled')
    await page.keyboard.press('Enter')
    await expect(box).toHaveValue('')
    await expect(page.getByText('STOPPED', { exact: true })).toBeVisible()
    await expect(chat.getByRole('button', { name: 'Stop' })).toHaveCount(0)

    // /coder: the chip, then the task; the Lead is asked to hand it on, and the sub-agent is asked for as before
    await box.fill('/cod')
    await page.keyboard.press('Tab')
    const chip = chat.locator('.composer-chip')
    await expect(chip).toHaveText(/^\/Coder/)
    await expect(box).toHaveAccessibleDescription(/Coder role/)
    await expect(box).toBeFocused()
    await reads(chip, 1)
    await page.keyboard.type('tidy the greeting')
    if (process.env.KOLONI_SHOTS) await shot(chat, `46-chip-${theme}`)
    const sent = page.waitForRequest(r => r.method() === 'POST' && /\/api\/conversations\/[0-9a-f]{32}\/messages$/.test(r.url()))
    await page.keyboard.press('Enter')
    expect((await sent).postDataJSON().content).toBe('Ask a sub-agent in the Coder role to do this: tidy the greeting')
    await expect(chip).toHaveCount(0)
    await expect(chat.getByText('Ask a sub-agent in the Coder role to do this: tidy the greeting')).toBeVisible()
    // the Lead asks for a Coder, and that is still the user's to let open
    await expect(chat.getByText('Open this sub-agent?')).toBeVisible({ timeout: 20_000 })
    await expect(chat.locator('.cmd-approval-where strong')).toHaveText('Coder')
    await expect(chat.getByText('tidy the greeting', { exact: true }).first()).toBeVisible()
    await box.fill('/stop')
    await page.keyboard.press('Enter')
    await expect(chat.getByText('Open this sub-agent?')).toHaveCount(0)
    // last: the list it opens is the browser's own (showPicker), and is left open
    await box.fill('/mode')
    await page.keyboard.press('Enter')
    await expect(chat.getByLabel('Permission level')).toBeFocused()
  })
