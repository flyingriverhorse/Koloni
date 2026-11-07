// Slice 32e in the browser: the Voice panel's Gemini tab against the real backend - the key is
// saved there and removed, and never comes back to the page. Google is never reached: the one
// request that would reach it (/api/voice/gemini/say) is answered by the test itself.
import { expect, test, type Page } from './fixtures'
import { contrasts, openFreshConversation, OWN, voiceSettings } from './helpers'

const KEY = 'AIza-test-key-0123456789'
const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })

// A key left saved would make every later spec read with Gemini.
test.afterEach(async ({ request }) => {
  await request.put('/api/voice/gemini', { headers: OWN, data: { api_key: '' } })
})

async function geminiTab(page: Page) {
  // (Never Google: a WAV header is enough for a sound that is not played.)
  await page.route('**/api/voice/gemini/say', route => route.fulfill({ status: 200, contentType: 'audio/wav', body: Buffer.from('RIFF') }))
  await openFreshConversation(page)
  // (Voice is The app's, in Settings: this browser's.)
  const panel = await voiceSettings(page)
  await panel.getByRole('tab', { name: 'Gemini' }).click()
  return panel
}

test('the Gemini key is saved from the panel and never shown again; removed, it is gone', async ({ page, request }) => {
  const panel = await geminiTab(page)
  await expect(panel).toContainText('Text read with Gemini is sent to Google. On the free tier Google may use it to improve its products; on a paid key it does not.')
  await expect(panel.getByLabel(/^Read aloud with Gemini/)).toBeDisabled()
  await panel.getByLabel('Gemini API key').fill(KEY)
  const saved = page.waitForResponse(response => response.url().endsWith('/api/voice/gemini') && response.request().method() === 'PUT')
  await panel.getByRole('button', { name: 'Save key' }).click()
  expect(await (await saved).text()).not.toContain(KEY)
  await expect(panel.getByText('A key is saved.')).toBeVisible()
  await expect(panel.getByLabel(/^Read aloud with Gemini/)).toBeChecked()
  expect(await page.content()).not.toContain(KEY)
  const shown = await request.get('/api/voice/gemini')
  expect(await shown.json()).toMatchObject({ has_key: true })
  expect(await shown.text()).not.toContain(KEY)

  await panel.getByRole('combobox', { name: 'Voice' }).selectOption('Puck')
  await expect.poll(async () => (await (await request.get('/api/voice/gemini')).json()).voice).toBe('Puck')

  await panel.getByRole('button', { name: 'Remove key' }).click()
  await expect(panel.getByLabel('Gemini API key')).toBeVisible()
  expect(await (await request.get('/api/voice/gemini')).json()).toMatchObject({ has_key: false })
})

/** A real WAV as Gemini gives it (24 kHz, mono, 16 bit): a tenth of a second of silence. */
function silence() {
  const data = 2400 * 2
  const wav = Buffer.alloc(44 + data)
  wav.write('RIFF', 0)
  wav.writeUInt32LE(36 + data, 4)
  wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20) // PCM
  wav.writeUInt16LE(1, 22) // mono
  wav.writeUInt32LE(24000, 24)
  wav.writeUInt32LE(48000, 28)
  wav.writeUInt16LE(2, 32)
  wav.writeUInt16LE(16, 34)
  wav.write('data', 36)
  wav.writeUInt32LE(data, 40)
  return wav
}

test('with a key saved Auto-read has Gemini read the answer a sentence a request as it comes, 🔊 all of it in one, played to the end in the browser', async ({ page, request }) => {
  await request.put('/api/voice/gemini', { headers: OWN, data: { api_key: KEY } })
  const asked: string[] = []
  await page.route('**/api/voice/gemini/say', route => {
    asked.push(route.request().postDataJSON().text)
    return route.fulfill({ status: 200, contentType: 'audio/wav', body: silence() })
  })
  await openFreshConversation(page)
  const chat = chatOf(page)
  await chat.getByRole('button', { name: 'Auto-read' }).click()
  await page.getByLabel('Message').fill('how is the total worked out?')
  await chat.getByRole('button', { name: 'Send' }).click()
  // Each asked for once the one before it sounds: all three, so each was played.
  await expect.poll(() => asked, { timeout: 20_000 }).toEqual(['The total adds the tax once.', 'It is twenty percent.', 'Code block, 1 line.'])
  await expect(chat.getByRole('button', { name: 'Read aloud' })).toBeVisible()
  await chat.getByRole('button', { name: 'Read aloud' }).click()
  await expect.poll(() => asked.slice(3)).toEqual(['The total adds the tax once. It is twenty percent. Code block, 1 line.'])
  // Played to its end: the button is 🔊 again, and nothing went wrong.
  await expect(chat.getByRole('button', { name: 'Read aloud' })).toBeVisible()
  await expect(chat.getByRole('alert')).toHaveCount(0)
})

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme the Gemini tab stands out from what it is on, with no key and with one (contrast 4.5 or more)`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const panel = await geminiTab(page)
    await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
    const low = async () => {
      const pieces = await panel.evaluate(contrasts)
      expect(pieces.length).toBeGreaterThanOrEqual(8)
      return pieces.filter(piece => piece.ratio < 4.5)
    }
    expect(await low()).toEqual([])
    await panel.getByLabel('Gemini API key').fill(KEY)
    await panel.getByRole('button', { name: 'Save key' }).click()
    await expect(panel.getByText('A key is saved.')).toBeVisible()
    expect(await low()).toEqual([])
  })
}
