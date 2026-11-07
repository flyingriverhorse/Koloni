import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { part, Row } from './part'

/** Where commands run, as this machine says it: which shell, and what 5.1 costs (K-pwsh; B-324: its Set-Content writes a BOM). */
function shellSaid(shell: string | null | undefined, shellNote: string | null | undefined) {
  if (shellNote) return ` ${shellNote}.`
  if (shell === 'Windows PowerShell') return ' PowerShell 7 not found: commands run in Windows PowerShell 5.1, where Set-Content writes a UTF-8 BOM — install PowerShell 7 to avoid it.'
  return shell ? ` Commands run in ${shell}.` : ''
}

interface Where {
  dockerAvailable: boolean
  dockerError: string | null
  shell?: string | null
  shellNote?: string | null
}

/** This project › Commands and secrets: where its commands run, and what of your secrets they may see. */
export function useCommands(project: Project, where: Where) {
  const runOn = useRunOn(project, where)
  const secrets = useSecrets(project)
  // The three of where they run are sent together, always; the rest only when changed.
  return {
    ...part({ ...runOn.patch, ...secrets.patch }, runOn.valid, null),
    changed: !runOn.valid || runOn.moved || Object.keys(secrets.patch).length > 0,
    take: runOn.take,
    view: (
      <>
        {runOn.view}
        {secrets.view}
      </>
    ),
  }
}

/** Where commands run: this machine, or a Docker container with its image and network. */
function useRunOn(project: Project, where: Where) {
  const kept = project.docker_image ?? ''
  const [location, setLocation] = useState(project.exec_location)
  const [image, setImage] = useState(kept)
  const [network, setNetwork] = useState(project.docker_network)
  // Already on Docker: keep the option selectable so the choice stays visible.
  const dockerSelectable = where.dockerAvailable || project.exec_location === 'docker'
  return {
    patch: { exec_location: location, docker_image: image.trim() || null, docker_network: network },
    valid: location === 'host' || image.trim() !== '',
    moved: location !== project.exec_location || image.trim() !== kept || network !== project.docker_network,
    take: (now: Project) => {
      setLocation(now.exec_location)
      setImage(now.docker_image ?? '')
      setNetwork(now.docker_network)
    },
    view: (
      <>
        <h2>Run commands on</h2>
        <label className="choice">
          <input type="radio" name="exec-location" checked={location === 'host'} onChange={() => setLocation('host')} />
          <span>
            This machine
            <span className="choice-note">Uses the project's own tools as they are. Commands are not isolated.{shellSaid(where.shell, where.shellNote)}</span>
          </span>
        </label>
        <label className={`choice${dockerSelectable ? '' : ' choice-disabled'}`}>
          <input type="radio" name="exec-location" checked={location === 'docker'} disabled={!dockerSelectable} onChange={() => setLocation('docker')} />
          <span>
            Docker container
            <span className="choice-note">A fresh container per command with this folder mounted. Only the folder is kept.</span>
          </span>
        </label>
        {/* One line under the choice; what Docker itself said is a click away. */}
        {!where.dockerAvailable && where.dockerError && (
          <div className="alert docker-down">
            <span>Docker is not running: a container cannot be chosen.</span>
            <Hint doc={GUIDE.settingsCommands}>{where.dockerError}</Hint>
          </div>
        )}
        {location === 'docker' && (
          <>
            <Row label="Image" htmlFor="docker-image">
              <input id="docker-image" className="input mono" value={image} onChange={e => setImage(e.target.value)} placeholder="python:3.12" />
            </Row>
            <label className="choice">
              <input type="checkbox" checked={network} onChange={e => setNetwork(e.target.checked)} />
              <span>Allow network access</span>
            </label>
          </>
        )}
      </>
    ),
  }
}

/** What of your secrets commands may see: each sent only when changed. */
function useSecrets(project: Project) {
  // (A server older than the page has no such fields yet: their defaults, on, until it is restarted - K-ayar-cokme; 101.)
  const hidden = project.hide_secrets ?? true
  const passed = project.pass_env ?? ''
  const planted = project.canary ?? true
  const [hideSecrets, setHideSecrets] = useState(hidden)
  const [passEnv, setPassEnv] = useState(passed)
  const [canary, setCanary] = useState(planted)
  return {
    patch: {
      ...(hideSecrets !== hidden && { hide_secrets: hideSecrets }),
      ...(passEnv.trim() !== passed && { pass_env: passEnv.trim() }),
      ...(canary !== planted && { canary }),
    },
    view: (
      <>
        <label className="choice">
          <input type="checkbox" checked={hideSecrets} onChange={e => setHideSecrets(e.target.checked)} />
          <span>
            Hide secret files from commands
            <span className="choice-note">
              In Docker and in Copilot’s sandbox, commands see secret files (.env, keys) as empty or blocked. Elsewhere, an
              agent’s read or search of one asks you first. Turn off only if a command must read one.
            </span>
          </span>
        </label>
        <Row
          label="Secret variables commands may see"
          htmlFor="pass-env"
          whyId="pass-env-more"
          doc={GUIDE.settingsCommands} why="Names, comma-separated. Any other variable named like a secret is held back from commands."
          warn={project.held_env?.length > 0 && <span id="pass-env-note" className="choice-note">Held back from commands: {project.held_env.join(', ')}</span>}
        >
          <input id="pass-env" className="input mono" value={passEnv} maxLength={2000} placeholder="OPENAI_API_KEY, NPM_TOKEN" aria-describedby="pass-env-note pass-env-more" onChange={e => setPassEnv(e.target.value)} />
        </Row>
        <label className="choice">
          <input type="checkbox" checked={canary} onChange={e => setCanary(e.target.checked)} />
          <span>
            Planted test key (canary)
            <span className="choice-note">
              Each message’s commands get a made-up key, <code>KOLONI_CANARY_KEY</code>, that no agent is told of. A command, web
              request, browser or MCP call that would send it out is refused and the work stops: a page, file or tool output the
              agent read may have told it to.
            </span>{' '}
            <Hint id="canary-more" doc={GUIDE.secrets}>
              Claude Code, Codex, Copilot and agy working with their own tools get it too, but KOLONİ sees only what reaches its
              hook before each tool: a web search of their own that asks nothing, a key sent without its name, encoded or from
              a file is not caught. Printed in a command’s output it is hidden, and nothing stops.
            </Hint>
          </span>
        </label>
      </>
    ),
  }
}
