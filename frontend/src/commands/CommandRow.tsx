import { TerminalWindow } from '@phosphor-icons/react'
import { useState } from 'react'
import { api } from '../api/client'
import type { Command } from '../api/types'
import { StatusLabel } from '../shell/StatusLabel'
import { TONE_COLOR, commandSeconds, commandStatus } from './commandStatus'
import { outputPreview } from './outputPreview'

/**
 * One command - in the chat, an agent's window and the side panel: what ran, how it ended, its output on demand, all of
 * it a click further (the canvas's Command node had it - the user's, 5 Nov), and Stop while it runs. A CLI's own command
 * that failed is on record as ended with no exit code, its call as failed: it reads as failed.
 */
export function CommandRow({ command, failed = false }: { command: Command; failed?: boolean }) {
  const [open, setOpen] = useState(false)
  const { label, tone } = failed && command.status === 'exited' && command.exit_code === null ? CLI_FAILED : commandStatus(command)
  const seconds = commandSeconds(command)
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
      {open && <CommandOutput command={command} />}
    </div>
  )
}

const CLI_FAILED = { label: 'failed (its CLI said so)', tone: 'del' as const }

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
