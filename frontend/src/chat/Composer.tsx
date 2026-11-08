import { Article, CaretDown, DotsThree, GearSix, ListChecks, PaperPlaneRight, Stop } from '@phosphor-icons/react'
import { type ClipboardEvent, type KeyboardEvent, type ReactNode, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { PermissionMode, Provider } from '../api/types'
import type { LoadModels } from '../models/ModelNameInput'
import { fold } from '../shell/fold'
import { CloseMore, usePanel } from '../shell/usePanel'
import { useApp } from '../state/store'
import { AutoRead, Dictate, ReadFailed } from '../voice/VoiceControls'
import { engine } from '../voice/engine'
import { keep, stored, useWidth } from '../views/TwoPane'
import { stopReading } from '../voice/voice'
import { AttachMenu, Chips, type Pending } from './Attach'
import { fromProject, linksIn, MAX_BYTES, MAX_FILES, sizeText, upload, VIDEO_HEAD } from './attachments'
import { Compare, type Second } from './Compare'
import { takeFrames } from './frames'
import { asCode } from './pastedCode'

/** The topic a message would go on with, as the line above the message box names it. */
export interface ComposerTopic {
  title: string
  /** A trigger's topic: its turns are started with nobody watching. */
  scheduled?: boolean
}

interface Props {
  running: boolean
  permissionMode: PermissionMode
  /**
   * `fresh`: the message starts a new topic. Otherwise it goes on with the one `topic` names. `overBudget`: the user's word to
   * start it over the month's budget. `files`: the files added to it (slice 85b), and whether they go into the project too.
   */
  onSend: (content: string, fresh: boolean, overBudget?: boolean, files?: { attachments: string[]; save_to_project: boolean }) => Promise<void>
  /**
   * The topic the next message goes on with; 'new' when there are turns but no topic of
   * the user's to go on with; null in a conversation with no turn yet (nothing is said).
   */
  topic?: ComposerTopic | 'new' | null
  /**
   * One other place the message could go instead, offered under the line: a trigger's
   * topic to write into, or the way back from one. Picking it changes `topic`.
   */
  other?: { label: string; onPick: () => void } | null
  /** What the choice of a new topic belongs to (the conversation): it is not kept for another. */
  scope?: string
  onStop: () => void
  onPermissionMode: (mode: PermissionMode) => void
  /** Each new message starts with a plan to approve first (slice 49). */
  planFirst?: boolean
  /** Turn Plan first on or off; without it there is nothing to set it on. */
  onPlanFirst?: (on: boolean) => void
  /** Where this project's commands run; decides whether full auto needs a warning. */
  location?: 'host' | 'docker'
  /** The conversation's model: its button, first under the message box. */
  model?: ReactNode
  /** Why the conversation's model will not be shown a picture, said on its chip before it is sent (B-119). */
  unseen?: string | null
  /** This chat's own settings (sample C), behind ⚙ at the end of the model's line (under More in a narrow chat): its teams, folders, page scripts, what runs without asking. */
  sheet?: ReactNode
  /** Another way to start a turn, last under More: a room ("Work together…"). */
  beside?: ReactNode
  /** Send the message to two models side by side (slice 54): the conversation's (`first`) and one chosen under More. */
  compare?: { providers: Provider[]; first: string; onCompare: (content: string, second: Second, fresh: boolean, overBudget?: boolean) => Promise<void>; onModels?: LoadModels }
  /** The Workspace window's button, at the end of the model's line (slice 42d). */
  workspace?: ReactNode
  /**
   * The closed chat's small box (slice 38e): the message box alone, one line, Enter sends.
   * The rest is hidden, not gone: a choice half made under More stays.
   */
  compact?: boolean
}

/**
 * A command of the `/` menu (slice 46): the keyboard's way to a button that is there already.
 * A role's does nothing when chosen: it becomes the chip, and the task is written after it.
 */
interface Command {
  name: string
  what: string
  /** Why it cannot be chosen now; null while it can. */
  off: string | null
  /** Done when chosen. */
  run?: () => void
  /** Or the buttons under the box it presses, in turn. */
  press?: string[]
  /** Or the permission level's list it opens. */
  level?: true
  /** Or the text it puts in the box (the user's own, slice 53). */
  fill?: string
  /** Named in full with what follows it ("/test-yaz login form"): it alone is meant. */
  called?: boolean
}

/** The commands' names: a role of one of these names is left out, not shown as a second one. */
const COMMANDS = ['new', 'room', 'stop', 'model', 'mode', 'plan', 'compare']

export function Composer({
  running,
  permissionMode,
  onSend,
  onStop,
  onPermissionMode,
  planFirst = false,
  onPlanFirst,
  location = 'host',
  model,
  unseen = null,
  sheet,
  beside,
  compare,
  workspace,
  topic = null,
  other = null,
  scope = '',
  compact = false,
}: Props) {
  // The conversation's own draft, from the store: it outlives this box. Before there is a
  // conversation, the project's: one written for a project does not turn up in another.
  const projectId = useApp(s => s.projectId)
  const key = scope || `new in ${projectId ?? ''}`
  const draft = useApp(s => s.drafts[key] ?? '')
  const setDraft = (text: string) => useApp.getState().setDraft(key, text)
  const [error, setError] = useState<string | null>(null)
  // The server said the project is over this month's budget: the message waits for the user's word, kept in the box.
  // (Kept by the draft's key: another conversation's message is not the one asked about.)
  // A comparison asked about is sent again by `again`; a message, by `send`, as the box holds it then.
  const [over, setOver] = useState<{ key: string; said: string; again?: () => Promise<void> } | null>(null)
  const [sending, setSending] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)
  // "New topic", chosen for the next message of one conversation; null while not chosen.
  const [freshIn, setFreshIn] = useState<string | null>(null)
  // A role named at the start ("/coder fix it", any case): the chip, and the task after it.
  // The longest name first: "/Docs writer x" is for Docs writer, not for Docs. (Not the Lead: the message goes to it anyway.)
  const roles = useApp(s => s.roles).filter(r => r.name !== 'Lead' && !COMMANDS.includes(fold(r.name)))
  // The user's own (slice 53), after the built-ins.
  // One named as a role made after it is hidden: the role's chip wins (the server refuses the name while the role is there).
  const own = useApp(s => s.ownCommands).filter(c => !roles.some(r => fold(r.name) === fold(c.name)))
  // What Esc left as it was written ("/tester"): text, not a chip, while the box starts with it.
  const [kept, setKept] = useState<string | null>(null)
  const role = kept && draft.startsWith(kept) ? null : [...roles].sort((a, b) => b.name.length - a.name.length).find(r => fold(draft.slice(0, r.name.length + 2)) === fold(`/${r.name} `)) ?? null
  const head = role ? draft.slice(0, role.name.length + 2) : ''
  const text = draft.slice(head.length)
  // The files added to the next message (slice 85b): the server's, as the conversation has them; those on their way here.
  const conv = useApp(s => (scope && s.conv?.conversation.id === scope ? s.conv : null))
  const files = conv?.attachments.filter(one => !one.message_id && !one.frame_of) ?? []
  const frames = Object.fromEntries(files.map(one => [one.id, conv!.attachments.filter(f => f.frame_of === one.id).length]))
  const [pending, setPending] = useState<Pending[]>([])
  // What was not added says so till the files it was refused beside change: one is taken off, or the message goes (B-106).
  const dropRefused = () => setPending(was => was.filter(one => !one.error))
  const [noFrames, setNoFrames] = useState<Record<string, string>>({})
  // "Save these to the project too" (slice 23): remembered for each project, ticked or not.
  const saveKey = `koloni-save-attachments:${conv?.conversation.project_id}`
  const [saves, setSaves] = useState<Record<string, boolean>>({})
  const save = saves[saveKey] ?? stored(saveKey, false, read => typeof read === 'boolean')
  const setSave = (on: boolean) => {
    keep(saveKey, on)
    setSaves(was => ({ ...was, [saveKey]: on }))
  }
  const [dropping, setDropping] = useState(false)
  const links = linksIn(text)
  // Videos whose frames are being taken: the message waits for them, else it would go without them.
  const [framing, setFraming] = useState(0)
  const going = pending.some(one => !one.error) || framing > 0
  const canSend = (text.trim().length > 0 || files.length > 0) && !sending && !going
  // What the line says is what is sent: a new topic by choice, or for want of one to go on with.
  const fresh = topic === 'new' || (topic !== null && freshIn === scope)

  // Code just pasted, put in the box fenced (slice 85a): the box then, and as it was pasted, for the way back.
  // Its note is shown till the box changes, or a few seconds on - kept while its link has the focus.
  const [pasted, setPasted] = useState<{ key: string; done: string; plain: string; at: number; language: string | null } | null>(null)
  const noted = pasted?.key === key && pasted.done === draft ? pasted : null
  const asPlain = useRef<HTMLButtonElement>(null)
  // Where the cursor goes once the box holds what was put in it.
  const caret = useRef<number | null>(null)
  useLayoutEffect(() => {
    if (caret.current === null) return
    input.current?.setSelectionRange(caret.current, caret.current)
    caret.current = null
  })
  useEffect(() => {
    if (!noted) return
    const gone = setTimeout(() => document.activeElement !== asPlain.current && setPasted(null), 8000)
    return () => clearTimeout(gone)
  }, [noted])

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    // A screenshot, or files copied (slice 85b): added to the message. (Cells copied from a sheet bring a
    // picture of themselves too: text that comes with it is pasted as text.)
    const copied = Array.from(event.clipboardData.files ?? [])
    if (copied.length && !event.clipboardData.getData('text/plain')) {
      event.preventDefault()
      return void add(copied)
    }
    const raw = event.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n')
    const code = asCode(raw)
    const before = text.slice(0, event.currentTarget.selectionStart)
    // Into a fence the user opened, it goes as it is.
    if (!code || (before.match(/^ {0,3}(```|~~~)/gm) ?? []).length % 2 === 1) return
    event.preventDefault()
    const after = text.slice(event.currentTarget.selectionEnd)
    // A fence on lines of its own.
    const fence = `${before && !before.endsWith('\n') ? '\n' : ''}${code.text}${after && !after.startsWith('\n') ? '\n' : ''}`
    // Put in as typing is (onChange takes it), so Ctrl+Z takes it out again; where the browser cannot, set.
    if (!document.execCommand?.('insertText', false, fence)) {
      stopReading()
      engine.stop()
      caret.current = before.length + fence.length
      setDraft(head + before + fence + after)
    }
    // (after the insert: onChange clears it)
    setPasted({ key, done: head + before + fence + after, plain: head + before + raw + after, at: before.length + raw.length, language: code.language })
  }

  /** The conversation files are added to: this one, or - before there is one - a new one, the words written so far taken along. */
  async function conversationFor(): Promise<string | null> {
    if (scope) return scope
    const written = draft
    await useApp.getState().newConversation()
    const made = useApp.getState().conv?.conversation.id ?? null
    if (made && written) {
      useApp.getState().setDraft(made, written)
      useApp.getState().setDraft(key, '')
    }
    return made
  }

  /** Files added to the next message: each goes up at once and its chip says what it is; a video's frames follow it. */
  async function add(chosen: File[]) {
    if (!chosen.length) return
    let room = MAX_FILES - files.length - pending.filter(one => !one.error).length
    const keyed = chosen.map(file => ({ file, key: `${file.name}\n${Math.random()}` }))
    const said = (key: string, error: string | null) => setPending(was => was.map(one => (one.key === key ? { ...one, error } : one)))
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
          const added = framesOnly ? await upload(cid, file.slice(0, VIDEO_HEAD), file.name, undefined, file.size) : await upload(cid, file, file.name)
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
      for (const [at, shot] of shots.entries()) useApp.getState().attached(await upload(cid, shot, `${file.name} frame ${at + 1}.jpg`, videoId))
    } catch (err) {
      const why = err instanceof Error ? err.message : errorText(err)
      if (file.size > MAX_BYTES) {
        // Not kept and no frames: nothing of it would reach a model, so it is taken off again.
        await useApp.getState().detach(videoId).catch(() => {})
        setPending(was => [...was, { key: `${file.name}\n${Math.random()}`, name: file.name, error: `not added: its frames could not be taken (${why})` }])
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

  async function send(overBudget = false) {
    if (!canSend) return
    // A fence that opens the task starts a line of its own: one after "do this: " would be no fence.
    const task = text.trim()
    const content = role ? `Ask a sub-agent in the ${role.name} role to do this:${/^(```|~~~)/.test(task) ? '\n' : ' '}${task}` : draft.trim()
    const from = key // the user may be in another conversation by the time it has gone
    stopReading()
    setSending(true)
    setError(null)
    setOver(null)
    try {
      // (Without the word, sent as before: two arguments; with files, four.)
      const added = files.length ? { attachments: files.map(one => one.id), save_to_project: save } : undefined
      await (added ? onSend(content, fresh, overBudget, added) : overBudget ? onSend(content, fresh, true) : onSend(content, fresh))
      // Only what was sent is cleared: words written meanwhile stay. (The files go with their message.)
      if (useApp.getState().drafts[from] === draft) useApp.getState().setDraft(from, '')
      setFreshIn(null)
      dropRefused()
    } catch (err) {
      const said = overBudget ? null : overWhat(err)
      if (said) setOver({ key: from, said })
      else setError(errorText(err))
    } finally {
      setSending(false)
    }
  }

  // Compare (slice 54), asked about the budget as a message is: the same card, then sent again with the word.
  async function compareOn(content: string, second: Second, overBudget = false) {
    const from = key
    try {
      // To the topic the line names, as a message (B-09: it went on with the last one).
      await (overBudget ? compare!.onCompare(content, second, fresh, true) : compare!.onCompare(content, second, fresh))
      // What was sent is cleared from the box: words written there meanwhile stay.
      if (useApp.getState().drafts[from] === content) useApp.getState().setDraft(from, '')
      setFreshIn(null)
    } catch (err) {
      const said = overBudget ? null : overWhat(err)
      if (!said) throw err
      setOver({
        key: from,
        said,
        again: async () => {
          setOver(null)
          setError(null)
          await compareOn(content, second, true).catch(again => setError(errorText(again)))
        },
      })
    }
  }

  // The `/` menu: open while the box holds one line that starts with `/` and names a command,
  // until Esc or the focus leaves - closed then till something is written.
  const list = useId()
  const row = useRef<HTMLDivElement>(null)
  // In a chat under ~380px wide (a row under ~360px; it was 290 before 📎 came down to this row) the mic and Auto-read
  // do not fit beside the level and Send: they go under More, and the row stays one line (B-106).
  const { measure, width: rowWidth } = useWidth()
  const rowRef = useCallback(
    (el: HTMLDivElement | null) => {
      row.current = el
      measure(el)
    },
    [measure],
  )
  const voiceInMore = rowWidth !== null && rowWidth <= 360
  const voice = (
    <>
      <AutoRead />
      <Dictate
        // Written where the cursor is: what is said takes the place of what was selected.
        onStart={() => {
          const at = input.current
          return { before: text.slice(0, at?.selectionStart ?? text.length), after: text.slice(at?.selectionEnd ?? text.length) }
        }}
        onText={said => setDraft(head + said)}
        onError={setError}
      />
    </>
  )
  const level = useRef<HTMLSelectElement>(null)
  const [shut, setShut] = useState<string | null>(null)
  const [at, setAt] = useState(0)
  // shortcut: pressed by class, a rename in ModelPicker/WorkTogether breaks /model, /room silently; upgrade to props if it bites.
  // shortcut: closed, the row under the box is hidden and so is what these open; upgrade by opening the chat first if asked.
  const closed = compact ? 'open the chat for this' : null
  const commands: Command[] = [
    { name: 'new', what: 'Start a new topic with the next message', off: topic === null || fresh ? 'it starts one anyway' : null, run: () => setFreshIn(scope) },
    {
      name: 'room',
      what: 'Open a room: agents work on one goal together',
      off: closed ?? (beside ? null : 'no room can be opened here yet'),
      press: ['.composer-more > button', '.composer-beside button'],
    },
    { name: 'stop', what: 'Stop the work in progress', off: running ? null : 'nothing is at work', run: onStop },
    { name: 'model', what: 'Choose this conversation’s model', off: closed ?? (model ? null : 'no model to choose yet'), press: ['.model-picker-button'] },
    {
      name: 'mode',
      what: 'Choose the permission level',
      off: closed,
      // Only the chooser: a higher level is still the user's own pick, sent from this page.
      level: true,
    },
    {
      name: 'plan',
      what: `Switch Plan first ${planFirst ? 'off' : 'on'}`,
      off: onPlanFirst ? null : 'there is no conversation to set it on',
      run: () => onPlanFirst?.(!planFirst),
    },
    {
      name: 'compare',
      what: 'Send the message to two models side by side',
      off: closed ?? (compare ? null : 'there is no model to compare with yet'),
      press: ['.composer-more > button', '.composer-compare button'],
    },
    ...roles.map(r => ({ name: r.name, what: `Ask the Orchestrator to hand a task to the ${r.name} role`, off: null })),
    ...own.map(c => {
      // Its name, then a space or a new line: what follows may take more lines.
      const called = fold(draft.slice(0, c.name.length + 1)) === fold(`/${c.name}`) && /\s/.test(draft.charAt(c.name.length + 1))
      const typed = called ? draft.slice(c.name.length + 2).trim() : ''
      const line = c.template.split('\n')[0]
      // (split/join, not replace: a `$&` typed stays as it was typed.)
      const filled = c.template.includes('{args}') ? c.template.split('{args}').join(typed) : [c.template, typed].filter(Boolean).join(' ')
      // As the role's chip; a role gone since leaves the text, not a "/Ghost" sent as words.
      const chip = c.role === null ? undefined : roles.find(r => fold(r.name) === fold(c.role!))
      return { name: c.name, what: c.description || (line.length > 80 ? `${line.slice(0, 79)}…` : line), off: null, fill: chip ? `/${chip.name} ${filled}` : filled, called }
    }),
  ]
  // shortcut: while an own command's text takes more lines, the arrows move in the menu, not between the lines; Esc frees them.
  const wanted = !role && shut !== draft && (/^\/[^\n]*$/.test(draft) || commands.some(c => c.called)) ? fold(draft.slice(1)) : null
  // Named in full first ("/mode" is not "/model"), then those it starts, then those holding it.
  const rank = (command: Command) => (command.called || fold(command.name) === wanted ? 0 : fold(command.name).startsWith(wanted ?? '') ? 1 : 2)
  const shown = wanted === null ? [] : commands.filter(c => c.called || fold(c.name).includes(wanted)).sort((a, b) => rank(a) - rank(b))
  const menu = shown.length > 0
  const active = Math.min(at, shown.length - 1)

  function openLevel() {
    level.current?.focus()
    try {
      level.current?.showPicker?.()
    } catch {
      // no list opened without a key or a click: the focus is on it, and the arrows choose
    }
  }

  function choose(command: Command) {
    if (command.off) return
    setAt(0)
    setKept(null)
    if (command.fill !== undefined) return setDraft(command.fill)
    if (!command.run && !command.press && !command.level) return setDraft(`/${command.name} `)
    setDraft('')
    command.run?.()
    if (command.level) openLevel()
    // What the button does, unless what it opens is open already.
    for (const selector of command.press ?? []) {
      const button = row.current?.querySelector<HTMLElement>(selector)
      if (button?.getAttribute('aria-expanded') !== 'true') button?.click()
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return
    if (menu && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault()
      return setAt((active + (event.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length)
    }
    // (Tab on one that is off is not taken: the focus moves on.)
    if (menu && !event.shiftKey && (event.key === 'Enter' || (event.key === 'Tab' && !shown[active].off))) {
      event.preventDefault()
      return choose(shown[active])
    }
    if (menu && event.key === 'Escape') {
      event.stopPropagation() // the menu's: the chat stays open
      setKept(draft)
      return setShut(draft)
    }
    // At the chip's edge Backspace takes the chip away.
    if (event.key === 'Backspace' && head && event.currentTarget.selectionStart === 0 && event.currentTarget.selectionEnd === 0) {
      event.preventDefault()
      return setDraft(text)
    }
    if (event.key !== 'Enter') return
    // (In the small box there is one line: Shift+Enter makes none, and sends nothing.)
    if (event.shiftKey && !compact) return
    event.preventDefault()
    if (!event.shiftKey) void send()
  }

  // Files dragged over the box: where they are dropped is shown (slice 85b).
  const carriesFiles = (event: { dataTransfer: DataTransfer | null }) => Array.from(event.dataTransfer?.types ?? []).includes('Files')
  return (
    <div
      className={compact ? 'composer composer-compact' : 'composer'}
      onDragOver={event => {
        if (!carriesFiles(event)) return
        event.preventDefault()
        setDropping(true)
      }}
      onDragLeave={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropping(false)
      }}
      onDrop={event => {
        if (!carriesFiles(event)) return
        event.preventDefault()
        setDropping(false)
        void add(Array.from(event.dataTransfer.files))
      }}
    >
      {dropping && (
        <div className="att-drop" aria-hidden="true">
          Drop files here to add them to your message
          <div className="att-drop-sub">code, images, PDF, Word, video · up to {MAX_BYTES / 2 ** 20} MB each; a larger video goes as its frames only</div>
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {over?.key === key && (
        <div role="group" aria-label={over.said} className="composer-warning composer-budget">
          <span role="alert">{over.said}. Send it anyway?</span>
          {/* (The question is where the focus goes; Cancel gives it back to the message.) */}
          <button type="button" className="btn btn-small" autoFocus onClick={() => void (over.again ? over.again() : send(true))}>
            Go on anyway
          </button>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => {
              setOver(null)
              input.current?.focus()
            }}
          >
            Cancel
          </button>
        </div>
      )}
      <ReadFailed />
      {/* (These in the small box too: a message sent from it starts a turn as well.) */}
      {permissionMode === 'full_auto' && location === 'host' && (
        <div role="note" className="composer-warning">
          Commands run on this machine without asking.
        </div>
      )}
      {/* Closed, where the message goes is said only where it is not the usual. */}
      {compact && topic !== null && topic !== 'new' && (fresh || topic.scheduled) && (
        <div className="composer-topic muted">{fresh ? 'Goes to a new topic' : `Goes to ${topic.title}, a trigger’s topic`}</div>
      )}
      <Chips
        files={files}
        frames={frames}
        noFrames={noFrames}
        links={links}
        pending={pending}
        unseen={unseen}
        onRemove={id => {
          dropRefused()
          void useApp.getState().detach(id).catch(err => setError(errorText(err)))
        }}
        onDismiss={dismissed => setPending(was => was.filter(one => one.key !== dismissed))}
      />
      {/* (Under the chips, not beside Send: there it pushed Send off the level's line.) */}
      {files.length > 0 && (
        <span className="muted att-count">
          {files.length} attached · {sizeText(files.reduce((sum, one) => sum + one.size, 0))}
        </span>
      )}
      {files.length > 0 && conv?.conversation.project_id && (
        <label className="att-save muted">
          <input type="checkbox" checked={save} onChange={e => setSave(e.target.checked)} />
          Save these to the project too <span className="att-save-where">(into <span className="mono">docs/attachments/</span>, without asking; undo takes them back)</span>
        </label>
      )}
      <div className="composer-field">
        {menu && (
          <ul
            id={list}
            role="listbox"
            aria-label="Commands"
            className="palette-list composer-commands"
            // The focus stays in the box: a click or its scrollbar, and Shift+Tab, do not take it here.
            tabIndex={-1}
            onMouseDown={event => event.preventDefault()}
          >
            {shown.map((command, index) => (
              <li
                key={command.name}
                id={`${list}-${index}`}
                role="option"
                aria-selected={index === active}
                aria-disabled={command.off ? true : undefined}
                className="palette-row"
                ref={index === active ? item => item?.scrollIntoView?.({ block: 'nearest' }) : undefined}
                onClick={() => choose(command)}
              >
                <span className="palette-name mono">/{command.name}</span>{' '}
                <span className="muted palette-kind">
                  {command.what}
                  {command.off && ` - ${command.off}`}
                </span>
              </li>
            ))}
          </ul>
        )}
        {/* The sign as well as the colour says it is a command. */}
        {role && (
          <span id={`${list}-chip`} className="tag tag-accent composer-chip">
            /{role.name}
            <span className="visually-hidden">: the Orchestrator is asked to hand this to the {role.name} role; Backspace at the start takes it away</span>
          </span>
        )}
        <textarea
          aria-label="Message"
          // A textbox, not a combobox: a textarea keeps its lines (ARIA in HTML allows it no role).
          aria-haspopup="listbox"
          aria-controls={menu ? list : undefined}
          aria-autocomplete="list"
          aria-activedescendant={menu ? `${list}-${active}` : undefined}
          aria-describedby={role ? `${list}-chip` : undefined}
          className="input composer-input"
          rows={compact ? 1 : Math.min(6, Math.max(1, text.split('\n').length))}
          ref={input}
          value={text}
          onChange={e => {
            // Writing, the user is no longer listening - nor dictating: what is typed would be written over.
            stopReading()
            engine.stop()
            setDraft(head + e.target.value)
            setAt(0)
            setShut(null)
            setPasted(null)
          }}
          onPaste={onPaste}
          onKeyDown={onKeyDown}
          // (Gone with the focus; written in again, it is back.)
          onBlur={() => setShut(draft)}
          placeholder={projectId ? 'Ask about this project or request a change…' : 'Ask anything - pick a folder with the folder button to work on files'}
        />
      </div>
      {/* (On the page before it says anything: a region that comes already filled is often not read out.) */}
      <div role="status" className="composer-pasted muted">
        {noted && (
          <>
            Pasted as code{noted.language && ` (${noted.language})`} ·{' '}
            <button
              type="button"
              ref={asPlain}
              className="link-btn"
              onClick={() => {
                caret.current = noted.at
                setPasted(null)
                setDraft(noted.plain)
                input.current?.focus()
              }}
              onBlur={() => setPasted(null)}
            >
              Paste as plain text
            </button>
          </>
        )}
      </div>
      {/* Under the message box, two lines, two jobs (the user's pick, sample C): what it runs on and where it goes; then 📎, how far it may go, the rest under More, and Send. */}
      <div className="composer-row" hidden={compact} ref={rowRef}>
        <div className="composer-line">
          {model}
          {/* The next message goes on with the topic it is in; pressed, it starts a new one (pressed again: it goes on). */}
          {topic !== null && topic !== 'new' && (
            <button
              type="button"
              className="btn btn-small composer-new-topic"
              aria-pressed={fresh}
              title={
                fresh
                  ? `Your next message starts a new topic: press again to go on with ${topic.title}`
                  : `Your next message goes on with ${topic.title}${topic.scheduled ? ', a trigger’s topic' : ''}: press to start a new topic`
              }
              onClick={() => setFreshIn(fresh ? null : scope)}
            >
              <Article size={14} className="composer-icon" aria-hidden />
              <span className="composer-words">New topic</span>
            </button>
          )}
          {/* Not while "New topic" is pressed: one choice is undone at a time. */}
          {other && (topic === 'new' || !fresh) && (
            <button type="button" className="btn btn-small composer-new-topic" title={other.label} onClick={other.onPick}>
              {other.label}
            </button>
          )}
          {workspace}
          {/* (On this line: the one below has no room to spare. Narrower, it is under More, as the voice is.) */}
          <Sheet sheet={sheet} shown={!voiceInMore} />
        </div>
        {/* One line down to a 240px chat (the user's report: two while a turn ran): what has words keeps its icon, name and tooltip where they do not fit. */}
        <div className="composer-controls">
          <AttachMenu
            projectId={scope ? (conv?.conversation.project_id ?? null) : projectId}
            onFiles={chosen => void add(chosen)}
            onProject={path => void addFromProject(path)}
            onError={setError}
            onType={() => input.current?.focus()}
          />
          {/* The levels by their short names (sample A), the chosen one's full name in its tooltip and description. */}
          <select
            ref={level}
            aria-label="Permission level"
            aria-describedby={`${list}-level`}
            title={LEVELS[permissionMode]}
            className="input composer-mode"
            value={permissionMode}
            onChange={e => onPermissionMode(e.target.value as PermissionMode)}
          >
            <option value="ask">Ask</option>
            <option value="auto_edit">Auto-edit</option>
            <option value="full_auto">Full auto</option>
          </select>
          {onPlanFirst && (
            <label className="composer-plan" title="Plan first: each new message gets a plan to approve before anything changes">
              <ListChecks size={14} className="composer-icon" aria-hidden />
              <input type="checkbox" role="switch" className="switch" checked={planFirst} onChange={e => onPlanFirst(e.target.checked)} />
              <span className="composer-words">Plan first</span>
            </label>
          )}
          <More voice={voiceInMore}>
            <Sheet sheet={sheet} shown={voiceInMore} />
            {voiceInMore && <span className="composer-actions">{voice}</span>}
            <span className="composer-beside">{beside}</span>
            {compare && (
              <span className="composer-compare">
                <Compare
                  providers={compare.providers}
                  first={compare.first}
                  content={draft}
                  onCompare={(content, second) => compareOn(content, second)}
                  onModels={compare.onModels}
                />
              </span>
            )}
          </More>
          <div className="composer-actions">
            {!voiceInMore && voice}
            {/* While a turn runs: Stop a square beside the button in Send's place, which then queues. */}
            {running && (
              <button type="button" className="icon-btn composer-stop" aria-label="Stop" title="Stop the work" onClick={onStop}>
                <Stop size={14} weight="fill" />
              </button>
            )}
            <button type="button" className="btn btn-primary" title={running ? 'Queue' : 'Send'} disabled={!canSend} onClick={() => void send()}>
              <PaperPlaneRight size={14} />
              <span className="composer-say">{running ? 'Queue' : 'Send'}</span>
            </button>
          </div>
        </div>
        {/* (The level's description, out of the line it is measured by.) */}
        <span id={`${list}-level`} className="visually-hidden">
          {LEVELS[permissionMode]}
        </span>
      </div>
    </div>
  )
}

/** Each level's full name: the select shows the short ones. */
const LEVELS: Record<PermissionMode, string> = { ask: 'Ask before changes', auto_edit: 'Auto-edit files', full_auto: 'Full auto' }

/** ⚙ Chat: this chat's own settings in one panel over the row (sample C); what in it goes elsewhere closes it first. */
function Sheet({ sheet, shown }: { sheet: ReactNode; shown: boolean }) {
  const { open, setOpen, close, button, panel } = usePanel()
  // Under More (a narrow row), what goes elsewhere folds More too.
  const closeMore = useContext(CloseMore)
  if (!sheet || !shown) return null
  return (
    <div className="allow-list chat-sheet-button">
      <button ref={button} type="button" className="btn btn-small" aria-expanded={open} aria-label="This chat’s settings" title="This chat’s settings" onClick={() => (open ? close() : setOpen(true))}>
        <GearSix size={14} className="composer-icon" aria-hidden />
        <span className="composer-words">Chat</span>
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="This chat" className="allow-list-panel chat-sheet-panel">
          <div className="kicker">This chat only</div>
          <CloseMore.Provider
            value={() => {
              close()
              closeMore()
            }}
          >
            {sheet}
          </CloseMore.Provider>
        </div>
      )}
    </div>
  )
}

/**
 * What else can be done with a message, folded under one button: Work together, Compare. Each opens its own panel over the
 * row; Esc there closes that panel, and the next Esc, the button or a click elsewhere
 * closes More, the focus back on its button - unless a panel in it stays open, keeping a
 * change not saved. (Hidden, not gone: a form half written in it stays.) `voice`: Auto-read and Dictate are in it
 * (a narrow row): a dot on its button says so, and its description.
 */
function More({ children, voice = false }: { children: ReactNode; voice?: boolean }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const id = useId()
  // Once a panel open in it has had its say on the same click (B-95: it may keep a change not saved,
  // and folded away with More it seemed saved): More folds only if that panel closed.
  const fold = useCallback(() => setTimeout(() => !box.current?.querySelector('.allow-list-panel') && setOpen(false)), [])

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) fold()
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [open, fold])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Escape' || !open) return
    // (Only More: the chat it is in stays open.)
    event.stopPropagation()
    setOpen(false)
    button.current?.focus()
  }

  return (
    <div className="composer-more" ref={box} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-expanded={open}
        aria-controls={id}
        aria-describedby={voice ? `${id}-voice` : undefined}
        title="More"
        onClick={() => (open ? fold() : setOpen(true))}
      >
        <DotsThree size={14} weight="bold" className="composer-icon" />
        <span className="composer-words">More</span>
        <CaretDown size={12} className="composer-words" />
      </button>
      {/* (Beside the button, not in it: its name stays "More".) */}
      {voice && (
        <span id={`${id}-voice`} className="visually-hidden composer-more-voice">
          Auto-read and Dictate are in here
        </span>
      )}
      <div id={id} className="composer-more-panel" hidden={!open}>
        <CloseMore.Provider
          value={() => {
            setOpen(false)
            button.current?.focus()
          }}
        >
          {children}
        </CloseMore.Provider>
      </div>
    </div>
  )
}
