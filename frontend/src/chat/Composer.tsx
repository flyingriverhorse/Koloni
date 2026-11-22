import { Article, CaretDown, DotsThree, GearSix, PaperPlaneRight } from '@phosphor-icons/react'
import { type ClipboardEvent, type KeyboardEvent, type ReactNode, type RefObject, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { PermissionMode, Provider } from '../api/types'
import type { LoadModels } from '../models/ModelNameInput'
import { CloseMore, usePanel } from '../shell/usePanel'
import type { ConvState } from '../state/applyEvent'
import { type ChatTab, useApp } from '../state/store'
import { AutoRead, Dictate, ReadFailed } from '../voice/VoiceControls'
import { engine } from '../voice/engine'
import { keep, stored } from '../views/TwoPane'
import { stopReading } from '../voice/voice'
import { AttachMenu, Chips } from './Attach'
import { linksIn, MAX_BYTES, sizeText } from './attachments'
import { leadQuestion } from './chatLine'
import { Compare, type Second } from './Compare'
import { ComposerStatus } from './ComposerStatus'
import { asCode } from './pastedCode'
import type { Checks } from './levels'
import { LevelMenu } from './LevelMenu'
import { type SlashCommand, useSlash } from './slashCommands'
import { useAttach } from './useAttach'

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
  /** Check what I said first (K-yargıç), the project's; without its setter (a plain chat) the level menu has no switch. */
  checkFirst?: boolean
  onCheckFirst?: (on: boolean) => void
  /** S10: Check after a change for this chat, in the level menu; none in a plain chat. */
  checks?: Checks
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
  /** What waits for you outside this chat (tek-ev §1): its count under the box, and what opens Ready for you. */
  waits?: { count: number; onOpen: () => void }
  /**
   * The closed chat's small box (slice 38e): the message box alone, one line, Enter sends.
   * The rest is hidden, not gone: a choice half made under More stays.
   */
  compact?: boolean
}

/**
 * What the empty box says. While the Orchestrator's question is open in the open chat, on its Chat tab, that it is
 * answered on its card and a message sent now is queued (0.1.4); closed, the chat's line says what it asks, and the
 * Talk and Notes tabs, over which the same box stands, do not show it.
 */
function placeholderOf(conv: ConvState | null, projectId: string | null, compact: boolean, tab: ChatTab, running: boolean, away: boolean): string {
  if (!compact && tab === 'Chat' && conv && leadQuestion(conv)) return 'Answer the question above, or queue a message…'
  // (☾ Away: a message of yours ends it.)
  if (away) return 'Write to come back…'
  if (running) return 'Queue a message for after this turn…'
  return projectId ? 'Ask about this project or request a change…' : 'Ask anything - pick a folder with the folder button to work on files'
}

export function Composer({
  running,
  permissionMode,
  onSend,
  onStop,
  onPermissionMode,
  planFirst = false,
  onPlanFirst,
  checkFirst = false,
  onCheckFirst,
  checks,
  location = 'host',
  model,
  unseen = null,
  sheet,
  beside,
  compare,
  workspace,
  waits,
  topic = null,
  other = null,
  scope = '',
  compact = false,
}: Props) {
  const { projectId, key, draft, setDraft } = useDraft(scope)
  const [error, setError] = useState<string | null>(null)
  // The server said the project is over this month's budget: the message waits for the user's word, kept in the box.
  // (Kept by the draft's key: another conversation's message is not the one asked about.)
  // A comparison asked about is sent again by `again`; a message, by `send`, as the box holds it then.
  const [over, setOver] = useState<{ key: string; said: string; again?: () => Promise<void> } | null>(null)
  const [sending, setSending] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const { fresh, setFreshIn } = useFresh(topic, scope)
  const conv = useApp(s => (scope && s.conv?.conversation.id === scope ? s.conv : null))
  const tab = useApp(s => s.chatTab)
  const away = useApp(s => !!projectId && s.away?.status === 'running' && s.away.project_id === projectId)
  // Where the `/` menu's commands press their buttons; the level's chooser.
  const row = useRef<HTMLDivElement>(null)
  const slash = useSlash({
    draft,
    setDraft,
    compact,
    running,
    onStop,
    noTopic: topic === null,
    fresh,
    startTopic: () => setFreshIn(scope),
    room: Boolean(beside),
    model: Boolean(model),
    compare: Boolean(compare),
    planFirst,
    onPlanFirst,
    row,
  })
  const { role, head, text, menu } = slash
  const { files, frames, pending, setPending, dropRefused, noFrames, going, dropping, drop, add, addFromProject } = useAttach({ conv, scope, draftKey: key, draft })
  const { save, setSave } = useSave(conv)
  const links = linksIn(text)
  const canSend = sendable(text, files.length, sending || going)
  const { noted, setPasted, asPlain, caret } = usePasted(key, draft, input)

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

  const list = useId()
  const voice = (
    <Dictate
      // Written where the cursor is: what is said takes the place of what was selected.
      onStart={() => {
        const at = input.current
        return { before: text.slice(0, at?.selectionStart ?? text.length), after: text.slice(at?.selectionEnd ?? text.length) }
      }}
      onText={said => setDraft(head + said)}
      onError={setError}
    />
  )

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return
    if (menu && slash.menuKey(event)) return
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

  return (
    <div className={compact ? 'composer composer-compact' : 'composer'} {...drop}>
      <Notes
        dropping={dropping}
        error={error}
        budget={over?.key === key ? over : null}
        onGoOn={() => void (over?.again ? over.again() : send(true))}
        onCancel={() => {
          setOver(null)
          input.current?.focus()
        }}
        warn={permissionMode === 'full_auto' && location === 'host'}
        goes={goesOf(compact, topic, fresh)}
      />
      {/* One framed box (0.1.5, "Kovan konsolu"): what the chat does now, the message, one row; under it, quiet words. */}
      <div className="composer-row" ref={row}>
        <div className="composer-box">
          {/* What the chat does now, over the box: ready (its model chosen there), at work with Stop, or waiting for your answer. */}
          <ComposerStatus conv={conv} compact={compact} running={running} onStop={onStop} model={model} />
          <Attached
            files={files}
            frames={frames}
            noFrames={noFrames}
            links={links}
            pending={pending}
            unseen={unseen}
            dropRefused={dropRefused}
            onError={setError}
            onDismiss={dismissed => setPending(was => was.filter(one => one.key !== dismissed))}
            save={conv?.conversation.project_id ? { on: save, set: setSave } : null}
          />
          <Field
            list={list}
            slash={slash}
            text={text}
            compact={compact}
            input={input}
            onText={value => {
              // Writing, the user is no longer listening - nor dictating: what is typed would be written over.
              stopReading()
              engine.stop()
              setDraft(head + value)
              setPasted(null)
            }}
            onPaste={onPaste}
            onKeyDown={onKeyDown}
            placeholder={placeholderOf(conv, projectId, compact, tab, running, away)}
          />
          <PastedNote
            noted={noted}
            asPlain={asPlain}
            onPlain={plain => {
              caret.current = plain.at
              setPasted(null)
              setDraft(plain.plain)
              input.current?.focus()
            }}
            onLeave={() => setPasted(null)}
          />
          <ComposerBar
            hidden={compact}
            attach={
              <AttachMenu
                projectId={scope ? (conv?.conversation.project_id ?? null) : projectId}
                onFiles={chosen => void add(chosen)}
                onProject={path => void addFromProject(path)}
                onError={setError}
                onType={() => input.current?.focus()}
              />
            }
            mode={permissionMode}
            onMode={onPermissionMode}
            planFirst={planFirst}
            onPlanFirst={onPlanFirst}
            checkFirst={checkFirst}
            onCheckFirst={onCheckFirst}
            checks={checks}
            dictate={voice}
            running={running}
            canSend={canSend}
            onSend={() => void send()}
          />
        </div>
        <ComposerBelow
          hidden={compact}
          workspace={workspace}
          topic={topic}
          fresh={fresh}
          onFresh={() => setFreshIn(fresh ? null : scope)}
          other={topic === 'new' || !fresh ? other : null}
          sheet={sheet}
          waits={waits}
        >
          <span className="composer-beside">{beside}</span>
          {compare && (
            <span className="composer-compare">
              <Compare providers={compare.providers} first={compare.first} content={draft} onCompare={(content, second) => compareOn(content, second)} onModels={compare.onModels} />
            </span>
          )}
        </ComposerBelow>
      </div>
    </div>
  )
}

/** The conversation's own draft, from the store: it outlives this box. Before there is a conversation, the project's: one written for a project does not turn up in another. */
function useDraft(scope: string) {
  const projectId = useApp(s => s.projectId)
  const key = scope || `new in ${projectId ?? ''}`
  const draft = useApp(s => s.drafts[key] ?? '')
  return { projectId, key, draft, setDraft: (text: string) => useApp.getState().setDraft(key, text) }
}

/** "New topic", chosen for the next message of one conversation (`freshIn`; null while not chosen): what the line says is what is sent - a new topic by choice, or for want of one to go on with. */
function useFresh(topic: ComposerTopic | 'new' | null, scope: string) {
  const [freshIn, setFreshIn] = useState<string | null>(null)
  return { fresh: topic === 'new' || (topic !== null && freshIn === scope), setFreshIn }
}

/** "Save these to the project too" (slice 23): remembered for each project, ticked or not. */
function useSave(conv: ConvState | null) {
  const saveKey = `koloni-save-attachments:${conv?.conversation.project_id}`
  const [saves, setSaves] = useState<Record<string, boolean>>({})
  const save = saves[saveKey] ?? stored(saveKey, false, read => typeof read === 'boolean')
  const setSave = (on: boolean) => {
    keep(saveKey, on)
    setSaves(was => ({ ...was, [saveKey]: on }))
  }
  return { save, setSave }
}

/** Words or files to send, and nothing on its way (a send, a file going up, a video's frames). */
const sendable = (text: string, files: number, busy: boolean) => (text.trim().length > 0 || files > 0) && !busy

type Pasted = { key: string; done: string; plain: string; at: number; language: string | null }

/**
 * Code just pasted, put in the box fenced (slice 85a): the box then, and as it was pasted, for the way back. Its note is
 * shown till the box changes, or a few seconds on - kept while its link has the focus. `caret`: where the cursor goes
 * once the box holds what was put in it.
 */
function usePasted(key: string, draft: string, input: RefObject<HTMLTextAreaElement | null>) {
  const [pasted, setPasted] = useState<Pasted | null>(null)
  const noted = pasted?.key === key && pasted.done === draft ? pasted : null
  const asPlain = useRef<HTMLButtonElement>(null)
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
  return { noted, setPasted, asPlain, caret }
}

/** Closed, where the message goes is said only where it is not the usual. */
function goesOf(compact: boolean, topic: ComposerTopic | 'new' | null, fresh: boolean): string | null {
  if (!compact || topic === null || topic === 'new' || !(fresh || topic.scheduled)) return null
  return fresh ? 'Goes to a new topic' : `Goes to ${topic.title}, a trigger’s topic`
}

/** The message box, with the chosen role's chip at its start and the `/` menu over it (slice 46). */
function Field(p: {
  list: string
  slash: ReturnType<typeof useSlash>
  text: string
  compact: boolean
  input: RefObject<HTMLTextAreaElement | null>
  onText: (text: string) => void
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
  placeholder: string
}) {
  const { menu, shown, active, choose, role } = p.slash
  const { input } = p
  return (
    <div className="composer-field">
      {menu && <SlashMenu id={p.list} shown={shown} active={active} onChoose={choose} />}
      {/* The sign as well as the colour says it is a command. */}
      {role && (
        <span id={`${p.list}-chip`} className="tag tag-accent composer-chip">
          /{role.name}
          <span className="visually-hidden">: the Orchestrator is asked to hand this to the {role.name} role; Backspace at the start takes it away</span>
        </span>
      )}
      <textarea
        aria-label="Message"
        // A textbox, not a combobox: a textarea keeps its lines (ARIA in HTML allows it no role).
        aria-haspopup="listbox"
        aria-controls={menu ? p.list : undefined}
        aria-autocomplete="list"
        aria-activedescendant={menu ? `${p.list}-${active}` : undefined}
        aria-describedby={role ? `${p.list}-chip` : undefined}
        className="input composer-input"
        rows={p.compact ? 1 : Math.min(6, Math.max(1, p.text.split('\n').length))}
        ref={input}
        value={p.text}
        onChange={e => {
          p.onText(e.target.value)
          p.slash.setAt(0)
          p.slash.setShut(null)
        }}
        onPaste={p.onPaste}
        onKeyDown={p.onKeyDown}
        // (Gone with the focus; written in again, it is back.)
        onBlur={() => p.slash.setShut(p.slash.head + p.text)}
        placeholder={p.placeholder}
      />
    </div>
  )
}

/** Under the message, after code was pasted (slice 85a): on the page before it says anything - a region that comes already filled is often not read out. */
function PastedNote({ noted, asPlain, onPlain, onLeave }: { noted: Pasted | null; asPlain: RefObject<HTMLButtonElement | null>; onPlain: (pasted: Pasted) => void; onLeave: () => void }) {
  return (
    <div role="status" className="composer-pasted muted">
      {noted && (
        <>
          Pasted as code{noted.language && ` (${noted.language})`} ·{' '}
          <button type="button" ref={asPlain} className="link-btn" onClick={() => onPlain(noted)} onBlur={onLeave}>
            Paste as plain text
          </button>
        </>
      )}
    </div>
  )
}

/** Over the box: files dropped on it, an error, the month's budget asked about, a reading that failed, Full auto's warning, where the message goes. */
function Notes(p: {
  dropping: boolean
  error: string | null
  budget: { said: string } | null
  onGoOn: () => void
  onCancel: () => void
  warn: boolean
  goes: string | null
}) {
  return (
    <>
      {p.dropping && (
        <div className="att-drop" aria-hidden="true">
          Drop files here to add them to your message
          <div className="att-drop-sub">code, images, PDF, Word, video · up to {MAX_BYTES / 2 ** 20} MB each; a larger video goes as its frames only</div>
        </div>
      )}
      {p.error && (
        <div role="alert" className="alert">
          {p.error}
        </div>
      )}
      {p.budget && (
        <div role="group" aria-label={p.budget.said} className="composer-warning composer-budget">
          <span role="alert">{p.budget.said}. Send it anyway?</span>
          {/* (The question is where the focus goes; Cancel gives it back to the message.) */}
          <button type="button" className="btn btn-small" autoFocus onClick={p.onGoOn}>
            Go on anyway
          </button>
          <button type="button" className="btn btn-small" onClick={p.onCancel}>
            Cancel
          </button>
        </div>
      )}
      <ReadFailed />
      {/* (These in the small box too: a message sent from it starts a turn as well.) */}
      {p.warn && (
        <div role="note" className="composer-warning">
          Commands run on this machine without asking.
        </div>
      )}
      {p.goes && <div className="composer-topic muted">{p.goes}</div>}
    </>
  )
}

/** In the box, over the message: the files added to it, how many and how big, and whether they go into the project too. */
function Attached({ files, save, dropRefused, onError, ...chips }: Omit<Parameters<typeof Chips>[0], 'onRemove'> & {
  dropRefused: () => void
  onError: (error: string) => void
  save: { on: boolean; set: (on: boolean) => void } | null
}) {
  return (
    <>
      <Chips
        files={files}
        {...chips}
        onRemove={id => {
          dropRefused()
          void useApp.getState().detach(id).catch(err => onError(errorText(err)))
        }}
      />
      {/* (Under the chips, not beside Send: there it pushed Send off the level's line.) */}
      {files.length > 0 && (
        <span className="muted att-count">
          {files.length} attached · {sizeText(files.reduce((sum, one) => sum + one.size, 0))}
        </span>
      )}
      {files.length > 0 && save && (
        <label className="att-save muted">
          <input type="checkbox" checked={save.on} onChange={e => save.set(e.target.checked)} />
          Save these to the project too <span className="att-save-where">(into <span className="mono">docs/attachments/</span>, without asking; undo takes them back)</span>
        </label>
      )}
    </>
  )
}

/** The `/` menu over the message (slice 46): its rows the palette's; the focus stays in the box. */
function SlashMenu({ id, shown, active, onChoose }: { id: string; shown: SlashCommand[]; active: number; onChoose: (command: SlashCommand) => void }) {
  return (
    <ul
      id={id}
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
          id={`${id}-${index}`}
          role="option"
          aria-selected={index === active}
          aria-disabled={command.off ? true : undefined}
          className="palette-row"
          ref={index === active ? item => item?.scrollIntoView?.({ block: 'nearest' }) : undefined}
          onClick={() => onChoose(command)}
        >
          <span className="palette-name mono">/{command.name}</span>{' '}
          <span className="muted palette-kind">
            {command.what}
            {command.off && ` - ${command.off}`}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The box's one row (0.1.5): 📎, the level's comb (Plan first is in its menu), then Auto-read, Dictate and Send (Queue while a turn runs). */
function ComposerBar(p: {
  hidden: boolean
  attach: ReactNode
  mode: PermissionMode
  onMode: (mode: PermissionMode) => void
  planFirst: boolean
  onPlanFirst?: (on: boolean) => void
  checkFirst: boolean
  onCheckFirst?: (on: boolean) => void
  checks?: Checks
  dictate: ReactNode
  running: boolean
  canSend: boolean
  onSend: () => void
}) {
  const say = p.running ? 'Queue' : 'Send'
  return (
    <div className="composer-bar" hidden={p.hidden}>
      {p.attach}
      <LevelMenu mode={p.mode} onMode={p.onMode} planFirst={p.planFirst} onPlanFirst={p.onPlanFirst} checkFirst={p.checkFirst} onCheckFirst={p.onCheckFirst} checks={p.checks} />
      <span className="composer-actions">
        <AutoRead />
        {p.dictate}
        <button type="button" className="btn btn-primary composer-send" title={say} disabled={!p.canSend} onClick={p.onSend}>
          <PaperPlaneRight size={14} />
          <span className="composer-say">{say}</span>
        </button>
      </span>
    </div>
  )
}

/**
 * Under the box, quiet words (0.1.5): Workspace first, New topic, the other place a message could go, Chat settings,
 * More - Work together and Compare -, and at the right what waits for you elsewhere.
 */
function ComposerBelow(p: {
  hidden: boolean
  workspace?: ReactNode
  topic: ComposerTopic | 'new' | null
  fresh: boolean
  onFresh: () => void
  other: Props['other']
  sheet?: ReactNode
  waits?: Props['waits']
  children: ReactNode
}) {
  const named = p.topic !== null && p.topic !== 'new' ? p.topic : null
  const row = useTight()
  return (
    <div ref={row} className="composer-below" hidden={p.hidden}>
      {p.workspace}
      {/* The next message goes on with the topic it is in; pressed, it starts a new one (pressed again: it goes on). */}
      {named && (
        <button
          type="button"
          className="btn btn-small composer-new-topic"
          aria-pressed={p.fresh}
          title={
            p.fresh
              ? `Your next message starts a new topic: press again to go on with ${named.title}`
              : `Your next message goes on with ${named.title}${named.scheduled ? ', a trigger’s topic' : ''}: press to start a new topic`
          }
          onClick={p.onFresh}
        >
          <Article size={14} className="composer-icon" aria-hidden />
          <span className="composer-words">New topic</span>
        </button>
      )}
      {/* Not while "New topic" is pressed: one choice is undone at a time. */}
      {p.other && (
        <button type="button" className="btn btn-small composer-other" title={p.other.label} onClick={p.other.onPick}>
          {p.other.label}
        </button>
      )}
      <Sheet sheet={p.sheet} />
      <More>{p.children}</More>
      <Waits waits={p.waits} />
    </div>
  )
}

/**
 * While the row under the box has no room for all its words, it is `data-tight`: "Chat settings" is "Settings" and what
 * waits "2 wait". Measured, not guessed from its width: after each render (what is in it may have changed) and as it is
 * resized. (Only the row is watched: its fewer words do not change its own size.)
 */
function useTight() {
  const row = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => fit(row.current))
  useLayoutEffect(() => {
    const at = row.current
    if (!at || typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(() => fit(at))
    watch.observe(at)
    return () => watch.disconnect()
  }, [])
  return row
}

function fit(row: HTMLElement | null) {
  if (!row) return
  delete row.dataset.tight
  if (row.scrollWidth > row.clientWidth) row.dataset.tight = ''
}

/** What waits for you outside this chat (tek-ev §1): its number and a few words, which open Ready for you. */
function Waits({ waits }: { waits?: Props['waits'] }) {
  if (!waits || waits.count <= 0) return null
  const verb = waits.count === 1 ? 'waits' : 'wait'
  return (
    <button type="button" className="link-btn composer-waits" aria-label={`Open Ready for you: ${waits.count} more ${verb} elsewhere`} onClick={waits.onOpen}>
      <b>{waits.count}</b> <span className="composer-waits-long">more {verb} elsewhere</span>
      <span className="composer-waits-short">{verb}</span>
    </button>
  )
}

/** ⚙ Chat settings: this chat's own settings in one panel over the row (sample C); what in it goes elsewhere closes it first. */
function Sheet({ sheet }: { sheet: ReactNode }) {
  const { open, setOpen, close, button, panel } = usePanel()
  // Under More (a narrow row), what goes elsewhere folds More too.
  const closeMore = useContext(CloseMore)
  if (!sheet) return null
  return (
    <div className="allow-list chat-sheet-button">
      <button ref={button} type="button" className="btn btn-small" aria-expanded={open} aria-label="This chat’s settings" title="This chat’s settings" onClick={() => (open ? close() : setOpen(true))}>
        <GearSix size={14} className="composer-icon" aria-hidden />
        <span className="composer-words">
          <span className="sheet-long">Chat settings</span>
          <span className="sheet-short">Settings</span>
        </span>
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
 * change not saved. (Hidden, not gone: a form half written in it stays.)
 */
function More({ children }: { children: ReactNode }) {
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
      <button ref={button} type="button" className="btn btn-small" aria-expanded={open} aria-controls={id} title="More" onClick={() => (open ? fold() : setOpen(true))}>
        <DotsThree size={14} weight="bold" className="composer-icon" />
        <span className="composer-words">More</span>
        <CaretDown size={12} className="composer-words" />
      </button>
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
