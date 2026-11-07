// Slice 32a in the browser: dictation into the message box, the Lead's answer read aloud as it
// is written or by its short line at the turn's end, and the Voice panel. The browser's speech
// objects are stood in for: what would be read aloud is written down, and what "is heard" is
// handed to the page by the test. Nothing is recorded.
import { expect, test, type Page } from './fixtures'
import { contrasts, openFreshConversation, settled, shot, voiceSettings } from './helpers'

declare global {
  interface Window {
    __said: string[]
    __hear: (text: string) => void
  }
}

/** Put in before the page's own scripts: Chromium's real objects would speak out loud, and listen. */
async function standIns(page: Page) {
  await page.addInitScript(() => {
    window.__said = []
    const queue: { onend: (() => void) | null; onerror: (() => void) | null }[] = []
    class Utterance {
      voice = null
      lang = ''
      rate = 1
      pitch = 1
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      text: string
      constructor(text: string) {
        this.text = text
      }
    }
    const voices = [
      { voiceURI: 'ava', name: 'Ava', lang: 'en-US', default: true, localService: true },
      { voiceURI: 'yelda', name: 'Yelda', lang: 'tr-TR', default: false, localService: true },
    ]
    const synth = {
      speak(utterance: Utterance) {
        window.__said.push(utterance.text)
        queue.push(utterance)
      },
      cancel() {
        queue.splice(0).forEach(utterance => utterance.onerror?.())
      },
      getVoices: () => voices,
      addEventListener() {},
      removeEventListener() {},
    }
    Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true })
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { value: Utterance, configurable: true })
    class Recognition {
      lang = ''
      continuous = false
      interimResults = false
      onresult: ((event: unknown) => void) | null = null
      onerror: ((event: unknown) => void) | null = null
      onend: (() => void) | null = null
      start() {
        window.__hear = text => this.onresult?.({ results: [[{ transcript: text }]] })
      }
      stop() {
        this.onend?.()
      }
    }
    Object.defineProperty(window, 'SpeechRecognition', { value: Recognition, configurable: true })
    Object.defineProperty(window, 'webkitSpeechRecognition', { value: Recognition, configurable: true })
  })
}

const said = (page: Page) => page.evaluate(() => window.__said)
const chatOf = (page: Page) => page.getByRole('region', { name: 'Chat' })

test('what is said is written into the message box and not sent; Auto-read reads the whole answer as it comes, its code as a code block', async ({ page }) => {
  await standIns(page)
  await openFreshConversation(page)
  const chat = chatOf(page)
  const posted: string[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/messages')) posted.push(request.postData() ?? '')
  })
  await chat.getByRole('button', { name: 'Dictate' }).click()
  await page.evaluate(() => window.__hear('how is the total worked out?'))
  await expect(page.getByLabel('Message')).toHaveValue('how is the total worked out?')
  await chat.getByRole('button', { name: 'Dictate' }).click()
  expect(posted).toEqual([])

  await chat.getByRole('button', { name: 'Auto-read' }).click()
  await expect(chat.getByRole('button', { name: 'Auto-read' })).toHaveAttribute('aria-pressed', 'true')
  await chat.getByRole('button', { name: 'Send' }).click()
  await expect.poll(() => said(page), { timeout: 20_000 }).toEqual(['The total adds the tax once.', 'It is twenty percent.', 'Code block, 1 line.'])
  // Not asked for a line to say, the Lead wrote none, and none is taken off.
  expect(JSON.parse(posted[0])).not.toHaveProperty('spoken')
  await expect(chat.getByText(/^Said aloud/)).toHaveCount(0)
  // Remembered in this browser.
  await page.reload()
  await expect(chatOf(page).getByRole('button', { name: 'Auto-read' })).toHaveAttribute('aria-pressed', 'true')
})

test('Auto-read of a short summary: the message asks for a line to say, it is kept off the written answer, read at the end of the turn and shown under it', async ({ page }) => {
  await standIns(page)
  await openFreshConversation(page)
  const chat = chatOf(page)
  // (Voice is The app's, in Settings: this browser's.)
  const panel = await voiceSettings(page)
  await expect(panel).toContainText('KOLONİ keeps no sound and sends none anywhere.')
  await panel.getByLabel(/^Short summary/).check()
  await panel.getByLabel('How the Orchestrator speaks').fill('short and friendly')
  await page.getByRole('button', { name: 'Close settings' }).click()
  await chat.getByRole('button', { name: 'Auto-read' }).click()
  await page.getByLabel('Message').fill('how is the total worked out?')
  const sent = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/messages'))
  await chat.getByRole('button', { name: 'Send' }).click()
  expect((await sent).postDataJSON().spoken).toEqual({ language: 'en-US', style: 'short and friendly' })
  await expect(chat.getByText('It adds the tax once, twenty percent.')).toBeVisible({ timeout: 20_000 })
  await expect(chat.locator('.msg-said')).toHaveText('Said aloud: It adds the tax once, twenty percent.')
  await expect(chat.locator('.msg-assistant')).not.toContainText('Say:')
  await expect.poll(() => said(page)).toEqual(['It adds the tax once, twenty percent.'])
  // While it is read (the stand-in never finishes), the answer's own button stops it; then it reads all of it.
  await chat.getByRole('button', { name: 'Stop reading' }).click()
  await chat.getByRole('button', { name: 'Read aloud' }).click()
  await expect(chat.getByRole('button', { name: 'Stop reading' })).toBeVisible()
  expect((await said(page)).slice(1)).toEqual(['The total adds the tax once.', 'It is twenty percent.', 'Code block, 1 line.'])
  await chat.getByRole('button', { name: 'Stop reading' }).click()
  await expect(chat.getByRole('button', { name: 'Read aloud' })).toBeVisible()
})

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme the voice controls, the Voice panel and what was said aloud stand out from what they are on (contrast 4.5 or more)`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.addInitScript(() => localStorage.setItem('koloni-voice', JSON.stringify({ autoRead: true, mode: 'summary' })))
    await standIns(page)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await page.getByLabel('Message').fill('how is the total worked out?')
    await chat.getByRole('button', { name: 'Send' }).click()
    await expect(chat.locator('.msg-said')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
    const low = async (root: ReturnType<Page['locator']>) => (await root.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)
    expect(await low(chat.locator('.msg-list'))).toEqual([])
    const panel = await voiceSettings(page)
    expect((await panel.evaluate(contrasts)).length).toBeGreaterThanOrEqual(10)
    expect(await low(panel)).toEqual([])
  })
}

// Taken on request (KOLONI_SHOTS=1): runtime/shots/32a-*.png.
for (const theme of ['light', 'dark'] as const)
  test(`shots: talking with KOLONİ by voice, slice 32a, ${theme}`, async ({ page }) => {
    test.skip(!process.env.KOLONI_SHOTS, 'screenshots are taken with KOLONI_SHOTS=1')
    await page.setViewportSize({ width: 1440, height: 900 })
    const snap = (name: string) => shot(page, `32a-${name}-${theme}`)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.addInitScript(() => localStorage.setItem('koloni-voice', JSON.stringify({ autoRead: true, mode: 'summary', style: 'short and friendly' })))
    await standIns(page)
    await openFreshConversation(page)
    const chat = chatOf(page)
    await chat.getByRole('button', { name: 'Dictate' }).click()
    await page.evaluate(() => window.__hear('how is the total worked out?'))
    await settled(page)
    await snap('dictating')
    await chat.getByRole('button', { name: 'Dictate' }).click()
    await chat.getByRole('button', { name: 'Send' }).click()
    await expect(chat.locator('.msg-said')).toBeVisible({ timeout: 20_000 })
    // (Being read: the stand-in never finishes, so the answer's button is ■.)
    await expect(chat.getByRole('button', { name: 'Stop reading' })).toBeVisible()
    await settled(page)
    await snap('said-aloud')
    await voiceSettings(page)
    await snap('voice-panel')
  })
