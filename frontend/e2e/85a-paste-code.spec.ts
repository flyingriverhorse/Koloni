// Slice 85a in the browser: code pasted into the message box is put there fenced, its language
// guessed and said under the box, a press away from the text as pasted; sent, it reaches the Lead
// fenced and stands in the user's own message as a coloured code box - in both themes.
import { expect, test, type Locator, type Page } from './fixtures'
import { contrasts, openFreshConversation, shot } from './helpers'

// (tall enough for the open chat to show the whole message in a shot)
test.use({ viewport: { width: 1440, height: 1400 } })

const CODE = 'import os\n\ndef greet85(name):\n    # say hello\n    return f"hi {name}"\n'

/** A paste as the browser makes one, from its own data: the machine's clipboard is not touched. */
const paste = (box: Locator, text: string) =>
  box.evaluate((element, text) => {
    const data = new DataTransfer()
    data.setData('text/plain', text)
    element.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, text)

for (const theme of ['light', 'dark'] as const) {
  test(`pasted code is fenced, can go back to plain text, and is sent and shown as code (${theme})`, async ({ page }: { page: Page }) => {
    await page.addInitScript(theme => localStorage.setItem('koloni-theme', theme), theme)
    await openFreshConversation(page)
    const box = page.getByLabel('Message')
    await box.focus()
    await paste(box, CODE)
    const fenced = `\`\`\`python\n${CODE.trimEnd()}\n\`\`\``
    await expect(box).toHaveValue(fenced)
    const note = page.getByRole('status').filter({ hasText: 'Pasted as code' })
    await expect(note).toBeVisible()
    // Put in as typing is: Ctrl+Z takes the paste out again, and the note with it.
    await box.press('Control+z')
    await expect(box).toHaveValue('')
    await expect(note).toHaveCount(0)
    await paste(box, CODE)
    await expect(box).toHaveValue(fenced)
    await expect(note).toHaveText('Pasted as code (python) · Paste as plain text')
    if (process.env.KOLONI_SHOTS) await shot(page.locator('.composer'), `85a-box-${theme}`)

    // Back to the text as pasted, and pasted again.
    await note.getByRole('button', { name: 'Paste as plain text' }).click()
    await expect(box).toHaveValue(CODE)
    await expect(box).toBeFocused()
    await box.fill('')
    await paste(box, CODE)
    await page.getByRole('button', { name: 'Send' }).click()

    // The Lead got it fenced; the user's message shows it as code, coloured.
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByText('I read your Python block.')).toBeVisible({ timeout: 20_000 })
    const bubble = chat.locator('.msg-user .msg-bubble')
    const code = bubble.locator('pre code.language-python')
    await expect(code).toContainText('def greet85(name):')
    await expect(code.locator('.hljs-keyword').first()).toHaveText('import')
    await expect(bubble).not.toContainText('```')
    expect((await bubble.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    if (process.env.KOLONI_SHOTS) await shot(bubble, `85a-message-${theme}`)
  })
}
