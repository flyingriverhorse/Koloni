import { useEffect, useId, useState } from 'react'
import { errorText } from '../api/client'
import type { Availability, ClaudeSessionSetup } from '../api/types'
import type { ProviderKind } from './ModelsPage'

/** A Copy button for a text shown beside it. */
export function Copy({ text, label = 'Copy the command' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState<'copied' | 'failed' | null>(null)
  // "Copied" is said for a moment, then the button is as it was.
  useEffect(() => {
    if (copied !== 'copied') return
    const back = setTimeout(() => setCopied(null), 3000)
    return () => clearTimeout(back)
  }, [copied])
  return (
    <>
      <button
        type="button"
        className="btn btn-small"
        aria-label={label}
        // (No clipboard on a page that is not served securely, or one the browser refuses.)
        onClick={() =>
          void (navigator.clipboard?.writeText(text) ?? Promise.reject()).then(
            () => setCopied('copied'),
            () => setCopied('failed'),
          )
        }
      >
        {copied === 'copied' ? 'Copied' : 'Copy'}
      </button>{' '}
      {copied === 'failed' && <span>Copy failed — select the text </span>}
    </>
  )
}

type RunCommand = NonNullable<Availability['install']>

/** A command for the user's own terminal, to copy, and its docs. KOLONİ never runs it. */
export function RunIt({ label, text, link, told }: { label: string; text: string; link: string; told: RunCommand }) {
  return (
    <div role="note" aria-label={label} className="composer-warning provider-note">
      {text}{' '}
      {told.cmd ? (
        // K-giris-cmd: cmd.exe takes no $env:, so its own form beside PowerShell's.
        [['PowerShell', told.command], ['Command Prompt', told.cmd]].map(([shell, command]) => (
          <div key={shell}>
            {shell}: <code className="mono">{command}</code> <Copy text={command} label={`Copy the ${shell} command`} />
          </div>
        ))
      ) : (
        <>
          <code className="mono">{told.command}</code> <Copy text={told.command} />
        </>
      )}
      <a href={told.docs} target="_blank" rel="noreferrer">
        {link}
      </a>
    </div>
  )
}

/** K-claude-hesap: logging in to a provider's own sign-in folder - in the user's own terminal, never in KOLONİ's. */
export function LogIn({ kind, told, onCheck }: { kind: ProviderKind; told: RunCommand; onCheck?: () => void }) {
  const [shown, setShown] = useState(false)
  const product = kind === 'claude_cli' ? 'Claude' : 'Codex'
  return (
    <div className="provider-note">
      <button type="button" className="btn btn-small" aria-expanded={shown} onClick={() => setShown(!shown)}>
        Log in to {product} for this provider
      </button>
      {shown && (
        <>
          <RunIt
            label={`How to log in to ${product} for this provider`}
            text={`Run this in your own ${told.cmd ? 'PowerShell or Command Prompt' : 'terminal'}. Log in there once; KOLONİ never sees the token.`}
            link="Sign-in docs"
            told={told}
          />
          {onCheck && (
            <button type="button" className="btn btn-small" title="Reads its sign-in again; no model is run" onClick={onCheck}>
              Check again
            </button>
          )}
        </>
      )}
    </div>
  )
}

/** Claude Code's reading kept fresh by the user's own sessions: the status line to add to its settings. KOLONİ never writes them. */
export function KeepFresh({ onSetup }: { onSetup: () => Promise<ClaudeSessionSetup> }) {
  // Undefined while it is read; a string: why it could not be.
  const [setup, setSetup] = useState<ClaudeSessionSetup | string>()
  useEffect(() => {
    let live = true
    onSetup().then(
      told => live && setSetup(told),
      err => live && setSetup(errorText(err)),
    )
    return () => {
      live = false
    }
  }, [onSetup])
  const line = typeof setup === 'object' ? `"statusLine": ${JSON.stringify({ type: 'command', command: setup.command })}` : null
  const heading = useId()
  return (
    <section aria-labelledby={heading} className="provider-note keep-fresh">
      <h3 id={heading}>Keep it fresh from your Claude Code sessions</h3>
      <p className="muted">
        Your own Claude Code sessions send what is left of your plan here through their status line as it changes (on Pro and Max, after a session’s first
        answer).
      </p>
      {typeof setup === 'string' && <div role="alert">The command could not be read: {setup}</div>}
      {line && (
        <p>
          Add this to your Claude Code settings yourself: open your Claude Code settings file,{' '}
          <code className="mono">%USERPROFILE%\.claude\settings.json</code>, add this line inside its outer <code className="mono">{'{ }'}</code> (with a
          comma between it and the line before), and save; Claude Code picks it up on its next refresh. <code className="mono">{line}</code>{' '}
          <Copy text={line} label="Copy the status line setting" />
        </p>
      )}
      <p className="muted">
        Already have a status line? End the command with <code className="mono">{'… --then \\"your command\\""}'}</code>; on Windows it runs under cmd.
      </p>
    </section>
  )
}
