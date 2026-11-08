import { Check, Checks, Key, X } from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { ToolCall } from '../api/types'

export type OutsideDecision = 'once' | 'folder' | 'reject'

const VERB: Record<string, string> = {
  read_file: 'read',
  list_dir: 'list',
  search: 'search in',
  write_file: 'change',
  edit_file: 'change',
  run_command: 'run a command that reaches',
}
/** What the backend's reason says of a file in a CLI's own folder in the home folder (K-ev-klasoru). */
const CLI_HOME = 'settings for this whole computer'
/** The calls that only look: their card opens a folder to read in, never to change files. */
const READS = new Set(['read_file', 'list_dir', 'search'])
/** A card's title's verb (sample A: each title a question): what the call does there. */
const ask = (call: ToolCall) => (READS.has(call.name) ? 'Read' : call.name === 'run_command' ? 'Run a command' : 'Change')

function argsOf(call: ToolCall): { path?: unknown; cwd?: unknown; access?: unknown; why?: unknown; name?: unknown } {
  try {
    return JSON.parse(call.arguments)
  } catch {
    return {}
  }
}

function pathOf(call: ToolCall): string {
  const args = argsOf(call)
  // (A command: the folder it runs in or names, where it really is.)
  const path = call.name === 'run_command' ? (call.outside_folder ?? args.cwd) : args.path
  return typeof path === 'string' ? path : ''
}

interface Props {
  call: ToolCall
  who: string
  onDecide: (decision: OutsideDecision) => Promise<void>
  /** The chat has no folder (slice 86b): a file the user named is read once, and no folder is offered. */
  plain?: boolean
}

/** The user's word on a card: busy while it is sent, and why it could not be. */
function useDecide(onDecide: Props['onDecide']) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(decision: OutsideDecision) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(decision)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, decide }
}

/** Asks before an agent opens a path outside the project and the folders it also works in - or for one it asks for beforehand. */
export function OutsideApproval(props: Props) {
  if (props.call.name === 'ask_folder') return <FolderAsked {...props} />
  if (props.call.name === 'ask_secret') return <SecretWanted {...props} />
  return props.call.why_asked ? <SecretAsked {...props} /> : <PathAsked {...props} />
}

/**
 * A secret file in the project (.env, a key) - or, in a chat with no folder, a file the user named: read only on your
 * word, this once. The card says why, in the backend's words.
 */
function SecretAsked({ call, who, onDecide, plain }: Props) {
  const { busy, error, decide } = useDecide(onDecide)
  // A file in a CLI's own folder (~/.codex), by the backend's reason for it (CLI_HOME_CARD) - in any chat.
  const home = !!call.why_asked?.includes(CLI_HOME)

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">
        {READS.has(call.name) ? 'Read' : 'Open'} {home ? 'this computer’s settings' : plain ? 'a file' : 'a secret file'}?
      </div>
      <div className="cmd-approval-where">
        {/* (In a plain chat: where the path really leads, a short name or `..` written out.) */}
        {who} wants to {VERB[call.name] ?? 'open'} <span className="mono">{call.outside_folder ?? pathOf(call)}</span>
      </div>
      <div className="cmd-approval-where">{call.why_asked}</div>
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
          <Check size={13} />
          Allow once
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      {home && (
        <div className="muted cmd-approval-note">
          Asked every time, at every permission level, and refused when nobody is watching. A key in it is a secret. One KOLONİ
          knows by its shape is hidden from the model. This CLI’s logins and past conversations are never opened.
        </div>
      )}
      {!plain && !home && (
        <div className="muted cmd-approval-note">
          A secret file is asked about every time, at every permission level: by KOLONİ’s file tools, by a command that names it
          and by a CLI’s own tools that ask KOLONİ first. agy started to only read does not ask. A script that does not name the
          file can still read it, unless the project’s commands keep secret files hidden (Settings › This project › Commands and secrets: in Docker
          or Copilot’s sandbox).
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

function PathAsked({ call, who, onDecide }: Props) {
  const { busy, error, decide } = useDecide(onDecide)
  const reads = READS.has(call.name)

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">{ask(call)} outside the project?</div>
      <div className="cmd-approval-where">
        {who} wants to {VERB[call.name] ?? 'open'} <span className="mono">{pathOf(call)}</span>, outside the project
      </div>
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
          <Check size={13} />
          Allow once
        </button>
        {/* Where the path really leads: what the conversation would work in from now on. None for a folder not there yet. */}
        {call.outside_folder && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('folder')}>
            <Checks size={13} />
            {reads ? 'Allow reading this folder' : 'Allow changes in this folder'}: <span className="mono">{call.outside_folder}</span>
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      <div className="muted cmd-approval-note">
        {reads
          ? '“Allow reading this folder” lets this conversation read there from now on; a change there is still asked about.'
          : '“Allow changes in this folder” lets this conversation work there from now on, at its permission level.'}{' '}
        A path outside the project is asked about at every permission level.
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/**
 * An agent asks beforehand for a folder outside the project (ask_folder), saying why: "Add to this chat" puts it on the
 * conversation's list, "This time" gives it to that agent alone (slice 86b).
 */
function FolderAsked({ call, who, onDecide }: Props) {
  const { busy, error, decide } = useDecide(onDecide)
  const { access, why } = argsOf(call)

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">Add a folder to this chat?</div>
      <div className="cmd-approval-where">
        {who} asks to {access === 'write' ? 'read and write in' : 'read in'} <span className="mono">{call.outside_folder ?? pathOf(call)}</span>
      </div>
      {typeof why === 'string' && <div className="cmd-approval-where">“{why}”</div>}
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('folder')}>
          <Checks size={13} />
          Add to this chat
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('once')}>
          <Check size={13} />
          This time
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      <div className="muted cmd-approval-note">
        {/* (why_asked: a CLI with tools of its own works there unheld - in the backend's words) */}
        {access === 'write'
          ? (call.why_asked ?? 'Read and write: as in the project, at this chat’s permission level.')
          : 'Read only: a change there is asked about every time.'}{' '}
        “Add to this chat”: no agent in this chat asks again. “This time”: only this agent, for this turn.
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/**
 * An agent asks, saying why, for a secret its commands need by its variable's name (ask_secret, slice 91). The value is
 * sent once from here, for that turn's commands only, and is never shown again - nor told to the model.
 */
function SecretWanted({ call, who }: Props) {
  // Uncontrolled: a controlled input would put the value in the page, as its value attribute.
  const field = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { name, why } = argsOf(call)

  async function send(give: boolean) {
    setBusy(true)
    setError(null)
    try {
      await api.post(`/tool-calls/${call.id}/secret`, { value: give ? (field.current?.value ?? '') : null })
      if (field.current) field.current.value = ''
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">Give a secret to its commands?</div>
      <div className="cmd-approval-where">
        {who} asks for <span className="mono">{String(name)}</span>
      </div>
      {typeof why === 'string' && <div className="cmd-approval-where">“{why}”</div>}
      {/* shortcut: no <form>, so nothing is submitted for a browser to offer to save; Chrome may still offer it - a text field drawn as dots (-webkit-text-security) if that is seen. */}
      <input
        ref={field}
        className="input mono"
        type="password"
        autoComplete="new-password"
        spellCheck={false}
        aria-label={`Value of ${String(name)}`}
        disabled={busy}
        onKeyDown={e => e.key === 'Enter' && void send(true)}
      />
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => send(true)}>
          <Key size={13} />
          Give
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => send(false)}>
          <X size={13} />
          Reject
        </button>
      </div>
      <div className="muted cmd-approval-note">
        Only the commands KOLONİ runs for this message get it, in their environment. If a command prints it as it is, it is
        hidden; a command you approve can still print it encoded, send it, or write it to a file. KOLONİ does not tell it to the
        model or keep it, and it is gone when the work on this message ends.
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
