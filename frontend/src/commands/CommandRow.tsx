import { TerminalWindow } from '@phosphor-icons/react'
import { useState } from 'react'
import { api } from '../api/client'
import type { Command } from '../api/types'
import { StatusLabel } from '../shell/StatusLabel'
import { JUDGED_FROM, TONE_COLOR, commandSeconds, commandStatus } from './commandStatus'
import { outputPreview } from './outputPreview'

/**
 * One command - in the chat, an agent's window and the side panel: what ran, how it ended, its output on demand, all of
 * it a click further (the canvas's Command node had it - the user's, 5 Nov), and Stop while it runs. A CLI's own command
 * that failed is on record as ended with no exit code, its call as failed: it reads as failed.
 */
export function CommandRow({
  command,
  failed = false,
  live = false,
}: {
  command: Command
  failed?: boolean
  live?: boolean
}) {
  const [picked, setOpen] = useState<boolean | null>(null)
  const { label, tone } =
    failed && command.status === 'exited' && command.exit_code === null ? CLI_FAILED : commandStatus(command)
  const seconds = commandSeconds(command)
  // In the chat (`live`): open while output comes and when it failed, until a click says otherwise.
  const open = picked ?? (live && (tone === 'del' || (command.status === 'running' && command.output !== '')))
  return (
    <div className="tool-row">
      <div className="tool-row-top">
        <button type="button" className="tool-row-head" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span style={{ color: TONE_COLOR[tone], display: 'grid' }}>
            <TerminalWindow size={13} className={command.status === 'running' ? 'pulse' : undefined} />
          </span>
          <span className="tool-row-summary mono">{command.command}</span>
          {command.origin === 'cli' && <span className="tool-row-status mono muted">own tool</span>}
          <StatusLabel color={TONE_COLOR[tone]}>{label}</StatusLabel>
          {seconds !== null && <span className="tool-row-status mono muted">{seconds}s</span>}
        </button>
        <StopCommand command={command} />
      </div>
      <OnYourWords judged={command.judged} />
      <JudgedRisky command={command} />
      <RanDisposable command={command} />
      {open && <CommandOutput command={command} />}
    </div>
  )
}

const CLI_FAILED = { label: 'failed (its CLI said so)', tone: 'del' as const }

/** A command that ran at Full auto with no card, or was not run, by the check of the user's own words: the line it rested on. */
function OnYourWords({ judged }: { judged: Command['judged'] }) {
  if (!judged || judged.verdict === 'ask' || !judged.source) return null
  return (
    <div className="tool-row-note muted">
      {judged.verdict === 'run' ? 'Ran without asking' : 'Not run'} · your rule: “{judged.quote}” (
      {JUDGED_FROM[judged.source]})
    </div>
  )
}

/** Full auto's judge (0.1.9): once its card is answered, the sentence it was asked on stays under the row, as the card
 *  said it - not while the card is open, nor for a "fine", which ran as Full auto runs any; one it refused (Refuse and go
 *  on), with its sentence. */
function JudgedRisky({ command }: { command: Command }) {
  const judged = command.judged
  if (judged?.kind !== 'risk' || command.status === 'proposed') return null
  if (judged.verdict !== 'risky' && judged.verdict !== 'refuse') return null
  return (
    <div className="tool-row-note muted" title={judged.model || undefined}>
      {`KOLONİ's judge${judged.verdict === 'refuse' ? ' refused' : ''}: ${judged.why || 'it gave no reason'}`}
    </div>
  )
}

/** Coordination §4: a delete that ran with no card, as KOLONİ found it disposable where the project allows such deletes - and, where it then failed, that it did (nothing may have gone: PowerShell's error for `rm -rf`, B). */
function RanDisposable({ command }: { command: Command }) {
  const disposable = command.disposable
  if (!disposable?.unasked) return null
  const failed =
    command.status === 'failed_to_start'
      ? 'did not start'
      : command.exit_code !== null && command.exit_code !== 0
        ? `failed: exit ${command.exit_code}`
        : null
  return (
    <div className="tool-row-note muted">
      {failed
        ? `Ran without asking as disposable (${disposable.what}) and ${failed}`
        : `Ran without asking · disposable: ${disposable.what}`}
    </div>
  )
}

/** Its output: the first and last lines, and all of it on "Show all". */
function CommandOutput({ command }: { command: Command }) {
  const [all, setAll] = useState(false)
  const preview = outputPreview(command.output)
  if (command.output === '')
    return (
      <div className="tool-row-detail">
        <pre className="mono muted">{command.status === 'running' ? '(no output yet)' : '(no output)'}</pre>
      </div>
    )
  return (
    <div className="tool-row-detail">
      <pre className="mono">{all ? command.output : preview.head}</pre>
      {preview.omitted > 0 && !all && (
        <>
          <div className="kicker">
            {preview.omitted} lines omitted{' '}
            <button type="button" className="link-btn" onClick={() => setAll(true)}>
              Show all
            </button>
          </div>
          <pre className="mono">{preview.tail}</pre>
        </>
      )}
    </div>
  )
}

/**
 * Stop while it runs: a server (slice 42b), with all it started; a CLI's own command (B-357), which ends that CLI's turn -
 * KOLONİ does not hold its process. (One already over says so on its record: nothing to add.)
 */
function StopCommand({ command }: { command: Command }) {
  const own = command.origin === 'cli' && (command.status === 'running' || command.status === 'approved')
  if (!own && (!command.keep_running || command.status !== 'running')) return null
  return (
    <button
      type="button"
      className="btn btn-small"
      aria-label={`Stop ${command.command}`}
      title={own ? 'Ends the turn of the CLI that runs it' : 'Stops the server, with everything it started'}
      onClick={() => void api.post(`/commands/${command.id}/stop`).catch(() => {})}
    >
      Stop
    </button>
  )
}
