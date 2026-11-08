/** The most frames taken of a video, as the server holds it (`MAX_FRAMES`). */
export const MAX_FRAMES = 8

/** When frames are taken: about one a second, at most `most`, evenly through it - each in the middle of its part. */
export function frameTimes(duration: number, most = MAX_FRAMES): number[] {
  const count = Math.min(most, Math.max(1, Math.round(duration)))
  return Array.from({ length: count }, (_, at) => (duration * (at + 0.5)) / count)
}

/** What frames are taken with; a test hands in its own. */
export interface Makers {
  video: () => HTMLVideoElement
  canvas: () => HTMLCanvasElement
}

const BROWSER: Makers = { video: () => document.createElement('video'), canvas: () => document.createElement('canvas') }

/**
 * Frames of a video, taken by the browser itself (slice 85b): it is opened in a `<video>` and
 * drawn on a `<canvas>` at each of `frameTimes`, as JPEG at most 1280 wide - nothing is
 * installed, nothing is sent anywhere. Throws, in words, where the browser cannot open it.
 */
export async function takeFrames(file: Blob, make: Makers = BROWSER): Promise<Blob[]> {
  const video = make.video()
  const url = URL.createObjectURL(file)
  video.muted = true
  video.preload = 'auto'
  try {
    const opened = once(video, 'loadedmetadata')
    video.src = url
    await opened
    if (!Number.isFinite(video.duration) || video.duration <= 0) throw new Error('its length could not be read')
    const canvas = make.canvas()
    const scale = Math.min(1, 1280 / (video.videoWidth || 1280))
    canvas.width = Math.round((video.videoWidth || 1280) * scale)
    canvas.height = Math.round((video.videoHeight || 720) * scale)
    const frames: Blob[] = []
    for (const time of frameTimes(video.duration)) {
      const seeked = once(video, 'seeked')
      video.currentTime = time
      await seeked
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
      frames.push(await new Promise<Blob>((done, failed) => canvas.toBlob(blob => (blob ? done(blob) : failed(new Error('a frame could not be drawn'))), 'image/jpeg', 0.85)))
    }
    return frames
  } finally {
    URL.revokeObjectURL(url)
    video.removeAttribute('src')
  }
}

/** How long a video may take to open, or to go to a time: the message waits for its frames. */
export const FRAME_SECONDS = 15

function once(video: HTMLVideoElement, event: string): Promise<void> {
  return new Promise((done, failed) => {
    const late = setTimeout(() => no('it did not open in time'), FRAME_SECONDS * 1000)
    const ok = () => {
      clearTimeout(late)
      video.removeEventListener('error', no)
      done()
    }
    const no = (why: unknown = 'this browser cannot open it') => {
      clearTimeout(late)
      video.removeEventListener(event, ok)
      failed(new Error(typeof why === 'string' ? why : 'this browser cannot open it'))
    }
    video.addEventListener(event, ok, { once: true })
    video.addEventListener('error', no, { once: true })
  })
}
