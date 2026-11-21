import { Article, CaretDown, DotsThree, GearSix, ListChecks, PaperPlaneRight } from '@phosphor-icons/react'
import { type ClipboardEvent, type KeyboardEvent, type ReactNode, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { PermissionMode, Provider } from '../api/types'
import type { LoadModels } from '../models/ModelNameInput'
import { CloseMore, usePanel } from '../shell/usePanel'
import type { ConvState } from '../state/applyEvent'
import { type ChatTab, useApp } from '../state/store'
import { AutoRead, Dictate, ReadFailed } from '../voice/VoiceControls'
import { engine } from '../voice/engine'
import { keep, stored, useWidth } from '../views/TwoPane'
import { stopReading } from '../voice/voice'
import { AttachMenu, Chips } from './Attach'
import { linksIn, MAX_BYTES, sizeText } from './attachments'
import { leadQuestion } from './chatLine'
import { Compare, type Second } from './Compare'
import { ComposerStatus } from './ComposerStatus'
import { asCode } from './pastedCode'
import { useSlash } from './slashCommands'
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
 * What the empty box says. While the Orchestrator's question is open in the open chat, on its Chat tab, that it is
 * answered on its card and a message sent now is queued (0.1.4); closed, the chat's line says what it asks, and the
 * Talk and Notes tabs, over which the same box stands, do not show it.
 */
function placeholderOf(conv: ConvState | null, projectId: string | null, compact: boolean, tab: ChatTab): string {
  if (!compact && tab === 'Chat' && conv && leadQuestion(conv)) return 'Answer the question above, or queue a message…'
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
  const conv = useApp(s => (scope && s.conv?.conversation.id === scope ? s.conv : null))
  const tab = useApp(s => s.chatTab)
  // What the line says is what is sent: a new topic by choice, or for want of one to go on with.
  const fresh = topic === 'new' || (topic !== null && freshIn === scope)
  // Where the `/` menu's commands press their buttons; the level's chooser.
  const row = useRef<HTMLDivElement>(null)
  const level = useRef<HTMLSelectElement>(null)
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
    openLevel,
  })
  const { role, head, text, menu, shown, active, choose } = slash
  const { files, frames, pending, setPending, dropRefused, noFrames, going, dropping, drop, add, addFromProject } = useAttach({ conv, scope, draftKey: key, draft })
  // "Save these to the project too" (slice 23): remembered for each project, ticked or not.
  const saveKey = `koloni-save-attachments:${conv?.conversation.project_id}`
  const [saves, setSaves] = useState<Record<string, boolean>>({})
  const save = saves[saveKey] ?? stored(saveKey, false, read => typeof read === 'boolean')
  const setSave = (on: boolean) => {
    keep(saveKey, on)
    setSaves(was => ({ ...was, [saveKey]: on }))
  }
  const links = linksIn(text)
  const canSend = (text.trim().length > 0 || files.length > 0) && !sending && !going

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
  function openLevel() {
    level.current?.focus()
    try {
      level.current?.showPicker?.()
    } catch {
      // no list opened without a key or a click: the focus is on it, and the arrows choose
    }
  }

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
    <div
      className={compact ? 'composer composer-compact' : 'composer'}
      {...drop}
    >
      {/* What the chat does now, over the box (0.1.5): ready, at work with Stop, or waiting for your answer. */}
      <ComposerStatus conv={conv} compact={compact} running={running} onStop={onStop} />
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
            slash.setAt(0)
            slash.setShut(null)
            setPasted(null)
          }}
          onPaste={onPaste}
          onKeyDown={onKeyDown}
          // (Gone with the focus; written in again, it is back.)
          onBlur={() => slash.setShut(draft)}
          placeholder={placeholderOf(conv, projectId, compact, tab)}
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
