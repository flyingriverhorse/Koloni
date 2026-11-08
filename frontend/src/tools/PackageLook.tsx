import { type ReactNode, useState } from 'react'
import { api, errorText } from '../api/client'
import type { CodeSeen, PackageAbout, PackageSeen } from '../api/types'
import { sizeText } from '../chat/attachments'

const REACHES: [key: string, label: string][] = [
  ['files', 'Files'],
  ['programs', 'Starting programs'],
  ['network', 'The network'],
  ['server', 'Serving on a port'],
  ['system', 'The system'],
]

const listed = (items: string[]) => (items.length > 0 ? <span className="mono">{items.join(', ')}</span> : <span className="muted">none seen</span>)

/**
 * What code says outright, read as text and never run (slice 92, app/package_look.py scan): what it may
 * reach, the programs, addresses and variables it names, and where it hides what it does. Never that it is
 * safe: what was seen, and what could not be.
 */
export function Seen({ seen, notSeen, children }: { seen: CodeSeen; notSeen: string[]; children?: ReactNode }) {
  const reaches = REACHES.filter(([key]) => seen.reaches[key]?.length)
  return (
    <div className="seen">
      {seen.hidden.length > 0 && (
        <div role="alert" className="alert">
          It hides what it does ({seen.hidden.join('; ')}): what is said below of it cannot be trusted.
        </div>
      )}
      <dl className="seen-list">
        <dt>It may reach</dt>
        <dd>
          {reaches.length > 0 ? (
            reaches.map(([key, label]) => (
              <span key={key} className="seen-reach">
                {label} (<span className="mono">{seen.reaches[key].join(', ')}</span>)
              </span>
            ))
          ) : (
            <span className="muted">none seen</span>
          )}
        </dd>
        <dt>Programs it names</dt>
        <dd>{listed(seen.programs)}</dd>
        <dt>Addresses it names</dt>
        <dd>{listed(seen.addresses)}</dd>
        <dt>Variables it reads</dt>
        <dd>
          {listed(seen.env)}
          {seen.whole_env && <div className="seen-warn">It reads its whole environment: every variable, keys among them.</div>}
        </dd>
        {children}
        <dt>Not seen</dt>
        <dd>
          <ul className="seen-unseen">
            {[...seen.unread, ...notSeen].map(line => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </dd>
      </dl>
      <p className="muted provider-note">
        From {seen.read} {seen.read === 1 ? 'file' : 'files'} of code read as text, none of it run. This is where to look,
        not a verdict: code can do what its text does not say outright.
      </p>
    </div>
  )
}

const from = (about: Pick<PackageAbout, 'registry'>) => (about.registry === 'npm' ? 'npm' : 'PyPI')

/**
 * "What does it do?" for the package npx or uvx is given, before the server is added or started: on a click
 * its registry is asked for its size (only its name is sent), and on a second it is downloaded and read as
 * text. Nothing of it is run.
 */
export function PackageLook({ spec, command }: { spec: string; command: string[] }) {
  const [about, setAbout] = useState<PackageAbout | null>(null)
  const [seen, setSeen] = useState<PackageSeen | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const size = about && (about.size === null ? 'size not listed' : `~${sizeText(about.size)}${about.unpacked ? ' unpacked' : ''}`)
  return (
    <section className="cmd-approval package-look" aria-label="What does it do?">
      <div className="kicker cmd-approval-kicker">What does it do?</div>
      {seen ? (
        <Seen
          seen={seen}
          notSeen={[
            `Its dependencies: ${seen.registry === 'npm' ? 'npx' : 'uvx'} installs and runs them too, and only ${seen.name} itself was read.`,
            'Paths, addresses and programs put together while it runs.',
          ]}
        >
          <dt>Runs when installed</dt>
          <dd>{listed(seen.on_install)}</dd>
          <dt>Brings with it</dt>
          <dd>{listed(seen.dependencies)}</dd>
          <dt>Read</dt>
          <dd>
            <span className="mono">
              {seen.name} {seen.version}
            </span>{' '}
            from {from(seen)}, {sizeText(seen.size)}, licence {seen.license ?? 'not listed'}
          </dd>
        </Seen>
      ) : about ? (
        <>
          <p className="cmd-approval-note">
            <span className="mono">
              {about.name} {about.version}
            </span>{' '}
            on {from(about)}, licence {about.license ?? 'not listed'}. It is downloaded into KOLONİ’s memory and read as
            text: none of it is run or kept.
          </p>
          <div className="change-actions">
            <button
              type="button"
              className="btn btn-small btn-primary"
              disabled={busy}
              autoFocus
              onClick={() =>
                void run(async () => setSeen(await api.post<PackageSeen>('/mcp-servers/package/look', { command, version: about.version })))
              }
            >
              Look inside (downloads {about.name}, {size})
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => setAbout(null)}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="cmd-approval-note">
            KOLONİ can download <span className="mono">{spec}</span> and read it without running it: what it may reach, and
            the programs, addresses and variables it names.
          </p>
          <div className="change-actions">
            <button
              type="button"
              className="btn btn-small"
              disabled={busy}
              onClick={() => void run(async () => setAbout(await api.post<PackageAbout>('/mcp-servers/package', { command })))}
            >
              Look inside…
            </button>
            <span className="muted provider-note">Asks its registry for its size first, sending only its name.</span>
          </div>
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
