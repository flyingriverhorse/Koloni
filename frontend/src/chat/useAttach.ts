import { type DragEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import type { Pending } from './Attach'
import { fromProject, MAX_BYTES, MAX_FILES, upload, VIDEO_HEAD } from './attachments'
import { takeFrames } from './frames'

/**
 * The files added to the next message (slice 85b): the server's, as the conversation has them; those on their way here,
 * each going up at once; a video's frames taken here; files dragged over the box. `scope`, `key`, `draft`: the
 * conversation the files go to - before there is one, a new one, the words written so far taken along.
 */
export function useAttach({
  conv,
  scope,
  draftKey,
  draft,
}: {
  conv: ConvState | null
  scope: string
  draftKey: string
  draft: string
}) {
  const files = conv?.attachments.filter(one => !one.message_id && !one.frame_of) ?? []
  const frames = Object.fromEntries(
    files.map(one => [one.id, conv!.attachments.filter(f => f.frame_of === one.id).length]),
  )
  const [pending, setPending] = useState<Pending[]>([])
  // What was not added says so till the files it was refused beside change: one is taken off, or the message goes (B-106).
  const dropRefused = () => setPending(was => was.filter(one => !one.error))
  const [noFrames, setNoFrames] = useState<Record<string, string>>({})
  const [dropping, setDropping] = useState(false)
  // Videos whose frames are being taken: the message waits for them, else it would go without them.
  const [framing, setFraming] = useState(0)
  const going = pending.some(one => !one.error) || framing > 0

  /** The conversation files are added to: this one, or - before there is one - a new one, the words written so far taken along. */
  async function conversationFor(): Promise<string | null> {
    if (scope) return scope
    const written = draft
    await useApp.getState().newConversation()
    const made = useApp.getState().conv?.conversation.id ?? null
    if (made && written) {
      useApp.getState().setDraft(made, written)
      useApp.getState().setDraft(draftKey, '')
    }
    return made
  }

  /** Files added to the next message: each goes up at once and its chip says what it is; a video's frames follow it. */
  async function add(chosen: File[]) {
    if (!chosen.length) return
    let room = MAX_FILES - files.length - pending.filter(one => !one.error).length
    const keyed = chosen.map(file => ({ file, key: `${file.name}\n${Math.random()}` }))
    const said = (key: string, error: string | null) =>
      setPending(was => was.map(one => (one.key === key ? { ...one, error } : one)))
    setPending(was => [...was, ...keyed.map(({ file, key }) => ({ key, name: file.name, error: null }))])
    let cid: string | null = null
    try {
      cid = await conversationFor()
    } catch (err) {
      return keyed.forEach(({ key }) => said(key, errorText(err)))
    }
    for (const { file, key } of keyed) {
      // A larger video goes as its frames alone: its first bytes say what it is, and none of it is kept.
      const framesOnly = file.size > MAX_BYTES && file.type.startsWith('video/')
      if (file.size > MAX_BYTES && !framesOnly) said(key, `larger than ${MAX_BYTES / 2 ** 20} MB: not added`)
      else if (room-- <= 0) said(key, `a message has ${MAX_FILES} files at most: not added`)
      else if (cid) {
        // One after another: the chips stand in the order the files were chosen.
        try {
          const added = framesOnly
            ? await upload(cid, file.slice(0, VIDEO_HEAD), file.name, undefined, file.size)
            : await upload(cid, file, file.name)
          setPending(was => was.filter(one => one.key !== key))
          useApp.getState().attached(added)
          // (Its frames held before its chip is done: Send never opens in between.)
          if (added.kind === 'video') void framesOf(cid, file, added.id)
        } catch (err) {
          said(key, errorText(err))
        }
      }
    }
  }

  /** Frames of a video, taken here in the browser, added beside it; where it cannot be opened its chip says so. */
  async function framesOf(cid: string, file: File, videoId: string) {
    setFraming(n => n + 1)
    try {
      const shots = await takeFrames(file)
      for (const [at, shot] of shots.entries())
        useApp.getState().attached(await upload(cid, shot, `${file.name} frame ${at + 1}.jpg`, videoId))
    } catch (err) {
      const why = err instanceof Error ? err.message : errorText(err)
      if (file.size > MAX_BYTES) {
        // Not kept and no frames: nothing of it would reach a model, so it is taken off again.
        await useApp
          .getState()
          .detach(videoId)
          .catch(() => {})
        setPending(was => [
          ...was,
          {
            key: `${file.name}\n${Math.random()}`,
            name: file.name,
            error: `not added: its frames could not be taken (${why})`,
          },
        ])
      } else setNoFrames(was => ({ ...was, [videoId]: `kept as a file; no frames: ${why}` }))
    } finally {
      setFraming(n => n - 1)
    }
  }

  async function addFromProject(path: string) {
    const key = `${path}\n${Math.random()}`
    setPending(was => [...was, { key, name: path.split('/').at(-1) ?? path, error: null }])
    try {
      const cid = await conversationFor()
      if (cid) useApp.getState().attached(await fromProject(cid, path))
      setPending(was => was.filter(one => one.key !== key))
    } catch (err) {
      setPending(was => was.map(one => (one.key === key ? { ...one, error: errorText(err) } : one)))
    }
  }

  // Files dragged over the box: where they are dropped is shown (slice 85b).
  const carriesFiles = (event: { dataTransfer: DataTransfer | null }) =>
    Array.from(event.dataTransfer?.types ?? []).includes('Files')
  const drop = {
    onDragOver: (event: DragEvent<HTMLDivElement>) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      setDropping(true)
    },
    onDragLeave: (event: DragEvent<HTMLDivElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropping(false)
    },
    onDrop: (event: DragEvent<HTMLDivElement>) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      setDropping(false)
      void add(Array.from(event.dataTransfer.files))
    },
  }

  return { files, frames, pending, setPending, dropRefused, noFrames, going, dropping, drop, add, addFromProject }
}
