import { api, withKey } from '../api/client'
import type { Attachment, Provider } from '../api/types'

/** As the server holds them (`app/attachments.py`): said here before a file is sent. */
export const MAX_BYTES = 25 * 2 ** 20
export const MAX_FILES = 10
/** What is sent of a larger video, to say it is one: it goes as its frames alone (`MAX_HEAD`). */
export const VIDEO_HEAD = 64 * 2 ** 10

/** One file or link as its chip and node show it. */
export interface Shown {
  /** On the coloured square: PNG, .ts, PDF, DOC, MP4, EXE, URL. */
  label: string
  /** The colour token of its kind. */
  colour: string
  /** What it is and what will happen to it, in a few words. */
  meta: string
}

const CODE = /\.(ts|tsx|js|jsx|mjs|cjs|py|rb|go|rs|java|kt|cs|c|h|cpp|hpp|php|swift|sh|ps1|sql|css|scss|html|vue|svelte|json|ya?ml|toml|xml)$/i

export function sizeText(size: number): string {
  return size < 1024 ? `${size} B` : size < 2 ** 20 ? `${Math.round(size / 1024)} KB` : `${(size / 2 ** 20).toFixed(1)} MB`
}

/** The providers whose models KOLONİ shows a picture to (`app/providers.py`: HTTP_KINDS, IMAGE_CLIS). */
const SEE_IMAGES: Provider['kind'][] = ['openai_compat', 'anthropic', 'claude_cli', 'codex_cli']

/** B-119: why the chat's model will not be shown a picture, said before it is sent; null: it may be. */
export const unseenOn = (provider: Provider | undefined) =>
  provider && !SEE_IMAGES.includes(provider.kind) ? `not shown: ${provider.name} is given no images by KOLONİ` : null

/**
 * A file as its chip says it: its kind, its size and what will happen to it. `frames`: those the page took of a video;
 * `unseen`: why the chat's model will not see a picture (`unseenOn`).
 */
export function shown(file: Attachment, frames = 0, noFrames: string | null = null, unseen: string | null = null): Shown {
  const ext = file.name.match(/\.[^.]+$/)?.[0] ?? ''
  const size = sizeText(file.size)
  // A picture's or video's, once sent: what became of it for each agent's model.
  const seen = Object.values(file.shown_to).join('; ') || null
  switch (file.kind) {
    case 'text': {
      const code = CODE.test(file.name)
      return { label: code ? ext.toLowerCase() : 'TXT', colour: '--file-code', meta: `${code ? 'code' : 'text'} · ${size} · ${file.summary}` }
    }
    case 'image':
      return { label: file.mime.split('/')[1].toUpperCase(), colour: '--file-img', meta: `image · ${size} · ${seen ?? unseen ?? 'seen by a model that sees images'}` }
    case 'pdf':
      return { label: 'PDF', colour: '--file-doc', meta: file.summary }
    case 'docx':
      return { label: 'DOC', colour: '--file-doc', meta: file.summary }
    case 'video':
      return {
        label: (ext.slice(1) || 'VID').toUpperCase(),
        colour: '--file-vid',
        meta: `video · ${size} · ${seen ?? noFrames ?? (frames ? `${file.size > MAX_BYTES ? 'not kept' : 'kept as a file'}, ${frames} frames taken` : 'taking frames…')}`,
      }
    case 'executable':
      return { label: 'EXE', colour: '--file-other', meta: `${size} · by name and size only: never read or run` }
    default:
      return { label: 'FILE', colour: '--file-other', meta: `${size} · ${file.summary}` }
  }
}

/** The links a message holds, each once: they become chips; the text stays as it is. Nothing is fetched. */
export function linksIn(text: string): string[] {
  const found = text.match(/https?:\/\/[^\s<>()"'`]+/g) ?? []
  return [...new Set(found.map(link => link.replace(/[.,;:!?]+$/, '')))]
}

/** A link as its chip names it: without its scheme. */
export const linkName = (link: string) => link.replace(/^https?:\/\//, '').replace(/\/$/, '')

export const LINK: Shown = { label: 'URL', colour: '--file-link', meta: 'a link · read only if an agent asks' }

/** One file for the conversation's next message, or a frame of a video of it; `size`: a larger video's, of which `file` is the first bytes. Throws ApiError. */
export function upload(conversationId: string, file: Blob, name: string, frameOf?: string, size?: number) {
  const query = new URLSearchParams({ name, ...(frameOf && { frame_of: frameOf }), ...(size && { size: String(size) }) })
  return api.upload<Attachment>(`/conversations/${conversationId}/attachments?${query}`, file)
}

/** A file of the chat's project, by its path. Throws ApiError. */
export function fromProject(conversationId: string, path: string) {
  return api.post<Attachment>(`/conversations/${conversationId}/attachments/project?${new URLSearchParams({ path })}`)
}

/** Where the page reads a file as it was added: with the page's key, as every other address of the API. */
export const fileUrl = (id: string) => withKey(`/api/attachments/${id}/file`)
