import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Attachment, Provider } from '../api/types'
import { resetStoreForTests, useApp } from '../state/store'
import { convState } from '../test-fixtures'
import { AttachmentPreview } from './Attach'
import { linksIn, shown, unseenOn } from './attachments'
import { Composer } from './Composer'
import { frameTimes, takeFrames } from './frames'

afterEach(() => {
  resetStoreForTests()
  vi.restoreAllMocks()
  localStorage.clear()
})

const props = {
  running: false,
  permissionMode: 'ask' as const,
  onSend: vi.fn().mockResolvedValue(undefined),
  onStop: vi.fn(),
  onPermissionMode: vi.fn(),
}

function file(id: string, over: Partial<Attachment> = {}): Attachment {
  return {
    id,
    conversation_id: 'c1',
    message_id: null,
    frame_of: null,
    name: `${id}.ts`,
    kind: 'text',
    mime: 'text/plain; charset=utf-8',
    size: 4096,
    summary: '132 lines',
    given_to: [],
    shown_to: {},
    keep_in_project: false,
    created_at: '2026-10-25T10:00:00Z',
    ...over,
  }
}

/** The composer of conversation c1, which has these files. */
function inChat(files: Attachment[], onSend = props.onSend) {
  const conv = convState({ attachments: files })
  useApp.setState({ conv: { ...conv, conversation: { ...conv.conversation, id: 'c1', project_id: 'p1' } } })
  return render(<Composer {...props} onSend={onSend} scope="c1" />)
}

describe('the chips of the next message', () => {
  test('each file says its kind, size and what will happen; a sent one and a frame are not chips', () => {
    inChat([
      file('cart'),
      file('shot', { name: 'shot.png', kind: 'image', mime: 'image/png' }),
      file('spec', { name: 'spec.pdf', kind: 'pdf', summary: '12 pages, text taken out' }),
      file('tool', { name: 'tool.exe', kind: 'executable' }),
      file('old', { message_id: 'm0' }),
      file('frame', { frame_of: 'clip', kind: 'image' }),
    ])
    const chips = within(screen.getByRole('list', { name: 'Attached' })).getAllByRole('listitem')
    expect(chips.map(chip => chip.textContent)).toEqual([
      '.tscart.tscode · 4 KB · 132 lines',
      'PNGshot.pngimage · 4 KB · seen by a model that sees images',
      'PDFspec.pdf12 pages, text taken out',
      'EXEtool.exe4 KB · by name and size only: never read or run',
    ])
    expect(screen.getByText('4 attached · 16 KB')).toBeInTheDocument()
  })

  test('× takes a file off; a link in the text is a chip too, and nothing is fetched', async () => {
    const removed = vi.spyOn(api, 'delete').mockResolvedValue(undefined)
    const fetched = vi.spyOn(globalThis, 'fetch')
    inChat([file('cart')])
    await userEvent.type(screen.getByLabelText('Message'), 'see https://stripe.com/docs/checkout.')
    expect(screen.getByText('stripe.com/docs/checkout')).toBeInTheDocument()
    expect(screen.getByText('a link · read only if an agent asks')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove cart.ts' }))
    expect(removed).toHaveBeenCalledWith('/attachments/cart')
    expect(screen.queryByText('cart.ts')).toBeNull()
    expect(fetched).not.toHaveBeenCalled()
  })

  test('the files go with the message by their ids, saved into the project when asked; with no words too', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    inChat([file('cart'), file('notes')], onSend)
    await userEvent.click(screen.getByLabelText(/Save these to the project too/))
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSend).toHaveBeenCalledWith('', false, false, { attachments: ['cart', 'notes'], save_to_project: true })
  })

  test('"Save these to the project too" is remembered for the project, not for another', async () => {
    inChat([file('cart')])
    await userEvent.click(screen.getByLabelText(/Save these to the project too/))
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByLabelText(/Save these to the project too/)).toBeChecked()
    cleanup()
    inChat([file('notes')])
    expect(screen.getByLabelText(/Save these to the project too/)).toBeChecked()
    cleanup()
    const conv = convState({ attachments: [file('other')] })
    useApp.setState({ conv: { ...conv, conversation: { ...conv.conversation, id: 'c1', project_id: 'p2' } } })
    render(<Composer {...props} scope="c1" />)
    expect(screen.getByLabelText(/Save these to the project too/)).not.toBeChecked()
  })

  test('a dropped file goes up at once; the drop zone shows while files are over the box', async () => {
    const sent = vi.spyOn(api, 'upload').mockResolvedValue(file('dropped', { name: 'dropped.ts' }))
    const { container } = inChat([])
    const box = container.querySelector('.composer')!
    const dropped = new File(['const x = 1\n'], 'dropped.ts')
    fireEvent.dragOver(box, { dataTransfer: { types: ['Files'], files: [dropped] } })
    expect(screen.getByText('Drop files here to add them to your message')).toBeInTheDocument()
    await act(async () => {
      fireEvent.drop(box, { dataTransfer: { types: ['Files'], files: [dropped] } })
    })
    expect(screen.queryByText('Drop files here to add them to your message')).toBeNull()
    expect(sent).toHaveBeenCalledWith('/conversations/c1/attachments?name=dropped.ts', dropped)
    expect(await screen.findByText('dropped.ts')).toBeInTheDocument()
  })

  test('while a video’s frames are being taken, the message waits for them', async () => {
    const clip = file('clip', { name: 'repro.mp4', kind: 'video', mime: 'video/mp4' })
    vi.spyOn(api, 'upload').mockResolvedValue(clip)
    URL.createObjectURL = vi.fn(() => 'blob:x') // (jsdom opens no video: its frames never come here)
    const { container } = inChat([])
    await userEvent.type(screen.getByLabelText('Message'), 'the bug')
    await act(async () => {
      fireEvent.drop(container.querySelector('.composer')!, { dataTransfer: { types: ['Files'], files: [new File(['mp4'], 'repro.mp4')] } })
    })
    expect(await screen.findByText('repro.mp4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  test('a file over 25 MB, or an eleventh, is not sent and its chip says why', async () => {
    const sent = vi.spyOn(api, 'upload')
    const { container } = inChat(Array.from({ length: 10 }, (_, at) => file(`f${at}`)))
    const big = new File(['x'], 'big.bin')
    Object.defineProperty(big, 'size', { value: 26 * 2 ** 20 })
    await act(async () => {
      fireEvent.drop(container.querySelector('.composer')!, { dataTransfer: { types: ['Files'], files: [big, new File(['y'], 'eleventh.txt')] } })
    })
    expect(await screen.findByText('larger than 25 MB: not added')).toBeInTheDocument()
    expect(screen.getByText('a message has 10 files at most: not added')).toBeInTheDocument()
    expect(sent).not.toHaveBeenCalled()
  })

  test('a video over 25 MB goes up as its first 64 KB and its size: its frames alone go on', async () => {
    const large = 30 * 2 ** 20
    const sent = vi.spyOn(api, 'upload').mockResolvedValue(file('long', { name: 'long.mp4', kind: 'video', mime: 'video/mp4', size: large }))
    URL.createObjectURL = vi.fn(() => 'blob:x')
    const { container } = inChat([])
    const long = new File([new Uint8Array(100 * 2 ** 10)], 'long.mp4', { type: 'video/mp4' })
    Object.defineProperty(long, 'size', { value: large })
    await act(async () => {
      fireEvent.drop(container.querySelector('.composer')!, { dataTransfer: { types: ['Files'], files: [long] } })
    })
    const [path, head] = sent.mock.calls[0]
    expect(path).toBe(`/conversations/c1/attachments?name=long.mp4&size=${large}`)
    expect((head as Blob).size).toBe(64 * 2 ** 10)
  })

  test('a video over 25 MB whose frames cannot be taken is taken off again: nothing of it would reach a model', async () => {
    const large = 30 * 2 ** 20
    vi.spyOn(api, 'upload').mockResolvedValue(file('long', { name: 'long.mp4', kind: 'video', mime: 'video/mp4', size: large }))
    const removed = vi.spyOn(api, 'delete').mockResolvedValue(undefined)
    URL.createObjectURL = vi.fn(() => {
      throw new Error('this browser cannot open it')
    })
    const { container } = inChat([])
    const long = new File(['mp4'], 'long.mp4', { type: 'video/mp4' })
    Object.defineProperty(long, 'size', { value: large })
    await act(async () => {
      fireEvent.drop(container.querySelector('.composer')!, { dataTransfer: { types: ['Files'], files: [long] } })
    })
    expect(await screen.findByText('not added: its frames could not be taken (this browser cannot open it)')).toBeInTheDocument()
    expect(removed).toHaveBeenCalledWith('/attachments/long')
    expect(within(screen.getByRole('list', { name: 'Attached' })).queryByText('video · 30.0 MB', { exact: false })).toBeNull()
  })

  test('a screenshot pasted into the box is added, not pasted as text', async () => {
    const sent = vi.spyOn(api, 'upload').mockResolvedValue(file('shot', { name: 'image.png', kind: 'image', mime: 'image/png' }))
    inChat([])
    const shot = new File(['png'], 'image.png', { type: 'image/png' })
    await act(async () => {
      fireEvent.paste(screen.getByLabelText('Message'), { clipboardData: { files: [shot], getData: () => '' } })
    })
    expect(sent).toHaveBeenCalledWith('/conversations/c1/attachments?name=image.png', shot)
    expect(screen.getByLabelText('Message')).toHaveValue('')
  })

  test('the 📎 menu offers the three ways; a file of the project needs a project', async () => {
    inChat([])
    await userEvent.click(screen.getByRole('button', { name: 'Attach' }))
    const items = screen.getAllByRole('menuitem').map(item => item.textContent?.trim())
    expect(items).toEqual(['Files from this computer…', 'A screenshot from the clipboard Ctrl+V', 'A file of the project…'])
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
  })
})

describe('what a file is said to be', () => {
  test('a video waits for its frames, then says how many; one the browser cannot open says so', () => {
    const clip = file('clip', { name: 'repro.mp4', kind: 'video', mime: 'video/mp4' })
    expect(shown(clip).meta).toBe('video · 4 KB · taking frames…')
    expect(shown(clip, 8).meta).toBe('video · 4 KB · kept as a file, 8 frames taken')
    expect(shown(clip, 0, 'kept as a file; no frames: this browser cannot open it').meta).toContain('cannot open it')
  })

  test('a video over 25 MB is not kept: no player for it, and its frames are what goes', () => {
    const long = file('long', { name: 'long.mp4', kind: 'video', mime: 'video/mp4', size: 30 * 2 ** 20, summary: 'frames only: larger than 25 MB, the video is not kept' })
    expect(shown(long, 3).meta).toBe('video · 30.0 MB · not kept, 3 frames taken')
    const { container } = render(<AttachmentPreview file={long} />)
    expect(container.querySelector('video')).toBeNull()
    expect(screen.getByText('frames only: larger than 25 MB, the video is not kept')).toBeInTheDocument()
    const kept = render(<AttachmentPreview file={file('clip', { name: 'repro.mp4', kind: 'video', mime: 'video/mp4' })} />)
    // (no Download in its controls: its address, with the page's key, would stay in the list of downloads)
    expect(kept.container.querySelector('video')).toHaveAttribute('controlslist', 'nodownload')
  })

  test('before it is sent, a picture says the chat’s model is shown none on a provider given no images (B-119)', () => {
    const shot = file('shot', { name: 'shot.png', kind: 'image', mime: 'image/png' })
    const copilot = { name: 'Copilot', kind: 'copilot_cli' } as Provider
    expect(shown(shot, 0, null, unseenOn(copilot)).meta).toBe('image · 4 KB · not shown: Copilot is given no images by KOLONİ')
    expect(unseenOn({ name: 'Claude', kind: 'claude_cli' } as Provider)).toBeNull()
    expect(shown(shot, 0, null, unseenOn(undefined)).meta).toBe('image · 4 KB · seen by a model that sees images')
  })

  test('once sent, a picture says what became of it for each agent’s model', () => {
    const shot = file('shot', { name: 'shot.png', kind: 'image', mime: 'image/png', shown_to: { a: 'shown to sonnet on Claude Code', b: 'not shown to q on Qoder: Qoder is given no images by KOLONİ' } })
    expect(shown(shot).meta).toBe('image · 4 KB · shown to sonnet on Claude Code; not shown to q on Qoder: Qoder is given no images by KOLONİ')
  })

  test('links are each found once, without the full stop after them', () => {
    expect(linksIn('a https://x.test/a, and http://y.test. and https://x.test/a again')).toEqual(['https://x.test/a', 'http://y.test'])
  })
})

describe('frames taken in the browser', () => {
  test('about one a second, at most eight, each in the middle of its part', () => {
    expect(frameTimes(2)).toEqual([0.5, 1.5])
    expect(frameTimes(80)).toEqual([5, 15, 25, 35, 45, 55, 65, 75])
    expect(frameTimes(0.2)).toEqual([0.1])
  })

  test('a video is opened, sought to each time and drawn', async () => {
    const listeners: Record<string, () => void> = {}
    const video = {
      duration: 3,
      videoWidth: 1920,
      videoHeight: 1080,
      set src(_value: string) {
        queueMicrotask(() => listeners.loadedmetadata?.())
      },
      set currentTime(_value: number) {
        queueMicrotask(() => listeners.seeked?.())
      },
      addEventListener: (event: string, run: () => void) => (listeners[event] = run),
      removeEventListener: () => {},
      removeAttribute: () => {},
    } as unknown as HTMLVideoElement
    const drawn: number[] = []
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: () => drawn.push(1) }),
      toBlob: (done: (blob: Blob) => void) => done(new Blob(['jpeg'])),
    } as unknown as HTMLCanvasElement
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const frames = await takeFrames(new Blob(['mp4']), { video: () => video, canvas: () => canvas })
    expect(frames).toHaveLength(3)
    expect(drawn).toHaveLength(3)
    expect([canvas.width, canvas.height]).toEqual([1280, 720])
  })

  test('one the browser cannot open says so', async () => {
    let failed: () => void = () => {}
    const video = {
      set src(_value: string) {
        queueMicrotask(() => failed())
      },
      addEventListener: (event: string, run: () => void) => event === 'error' && (failed = run),
      removeEventListener: () => {},
      removeAttribute: () => {},
    } as unknown as HTMLVideoElement
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    await expect(takeFrames(new Blob(['?']), { video: () => video, canvas: () => document.createElement('canvas') })).rejects.toThrow('this browser cannot open it')
  })
})
