import { CaretDown } from '@phosphor-icons/react'
import { type ChangeEvent, type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { Role, Skill, SkillPreview, SkillRecordRow, SkillSource, SkillUpload } from '../api/types'
import { Licence, ScriptsLeave, SkillShown, SkillText } from '../agents/SkillApproval'
import type { RoleChange } from '../agents/RolePanel'
import { cannotRun, SkillWindow } from '../agents/SkillWindow'
import { useConfirm } from '../shell/Confirm'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { count } from './paste'

/** What a skill may hold (app.skills.MAX_BYTES): a larger pick is refused here, before it is sent. */
const MAX_SKILL_BYTES = 5 * 1024 * 1024
/** A .zip may be larger (app.skills.MAX_ZIP_ENCODED): its .git and node_modules are left out unread, the rest held to 5 MiB there. */
const MAX_ZIP_BYTES = 25 * 1024 * 1024
// Not sent: the folders a skill's folder is read without (app.workspace.SKIP_DIRS); the app judges the rest again.
const NOT_SENT = /(^|\/)(\.git|node_modules|\.venv|__pycache__)\//

/** A file's bytes as base64 (a data URL's tail: no string of the whole file is built by hand). */
const base64 = (file: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).replace(/^[^,]*,/, ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })

/** A chosen folder's files (by the path the browser gives each), or a .zip, as the app takes them. */
// shortcut: a browser may follow a link in a chosen folder and send what it leads to (a File cannot tell one); the
// folder's note says so, and a .zip or the folder path keeps links out.
async function uploadOf(files: File[], zip: boolean): Promise<SkillUpload> {
  const sent = zip ? files.slice(0, 1) : files.filter(file => !NOT_SENT.test(file.webkitRelativePath))
  const size = sent.reduce((sum, file) => sum + file.size, 0)
  const mib = (bytes: number) => (bytes / 1024 / 1024).toFixed(1)
  if (zip && size > MAX_ZIP_BYTES) throw new Error(`A skill’s .zip is at most 25 MiB; this is ${mib(size)} MiB.`)
  if (!zip && size > MAX_SKILL_BYTES) throw new Error(`A skill holds at most 5 MiB; this is ${mib(size)} MiB. Choose the skill’s own folder.`)
  if (zip) return { zip: await base64(sent[0]) }
  return { files: await Promise.all(sent.map(async file => ({ path: file.webkitRelativePath || file.name, data: await base64(file) }))) }
}

/** A folder, a .zip or a GitHub repository, read and shown - its scripts whole, its licence, what is not copied - before its skill is kept. */
function AddSkill({
  onPreview,
  onAdd,
  kept,
  onCancel,
}: {
  onPreview: (source: SkillSource) => Promise<SkillPreview>
  onAdd: (source: SkillSource, unasked: boolean, sha256: string, replace: boolean) => Promise<void>
  /** The names of the skills kept already (a name is one whatever its case, as app/skills.py `named` has it). */
  kept: string[]
  /** Put away (opened from the Add menu at the page's top). */
  onCancel: () => void
}) {
  const [folder, setFolder] = useState('')
  const [github, setGithub] = useState('')
  // What was read, and from where: a repository's by the commit it was read at.
  const [found, setFound] = useState<{ skill: SkillPreview; from: SkillSource } | null>(null)
  const [unasked, setUnasked] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(action: () => Promise<void>) {
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
  const read = (source: SkillSource | Promise<SkillSource>) =>
    void act(async () => {
      const from = await source
      const skill = await onPreview(from)
      if (skill) setFound({ skill, from: 'github' in from ? { github: skill.source } : from })
    })
  const replacing = !!found && kept.some(name => name.toLowerCase() === found.skill.name.toLowerCase())
  const folderPick = useRef<HTMLInputElement>(null)
  const zipPick = useRef<HTMLInputElement>(null)
  const upload = (zip: boolean) => (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = '' // (so the same pick again is read again)
    if (files.length > 0) read(uploadOf(files, zip).then(upload => ({ upload })))
  }
  // (Enter reads: it does not save the role around it.)
  const enter = (source: SkillSource | null) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    if (source) read(source)
  }

  return (
    // (Not a fold: its line, clicked, put the form away - the user's, 6 Nov. Cancel does.)
    <section aria-labelledby="skill-add-title">
      <div id="skill-add-title" className="kicker">
        Add a skill
      </div>
      <div className="field">
        <label htmlFor="skill-folder">Skill folder</label>
        <input
          id="skill-folder"
          // (Shown only when asked for, from the Add menu: what is asked for takes the focus.)
          autoFocus
          className="input mono"
          value={folder}
          placeholder="The full path of a folder with a SKILL.md"
          aria-describedby="skill-folder-note"
          onChange={e => {
            setFolder(e.target.value)
            setFound(null)
          }}
          onKeyDown={enter(folder.trim() ? { folder: folder.trim() } : null)}
        />
        <span id="skill-folder-note" className="choice-note">
          KOLONİ keeps a copy in its own store, which no agent writes, so a later change to the folder does not change the
          skill. Secrets (a .env, a key, a credentials file) and links are not copied. A folder or a .zip chosen here is
          uploaded from this browser (5 MiB at most) and read the same way. But with Choose folder… a browser may follow a
          link and send what it points to: to keep links out, type the folder’s path or upload a .zip.
        </span>
      </div>
      <button type="button" className="btn btn-small" disabled={busy || !folder.trim()} onClick={() => read({ folder: folder.trim() })}>
        Read the folder
      </button>{' '}
      <button type="button" className="btn btn-small" disabled={busy} onClick={() => folderPick.current?.click()}>
        Choose folder…
      </button>{' '}
      <button type="button" className="btn btn-small" disabled={busy} onClick={() => zipPick.current?.click()}>
        Upload .zip…
      </button>
      {/* (webkitdirectory: not in React's types, but every browser's folder picker) */}
      <input ref={folderPick} type="file" hidden multiple {...{ webkitdirectory: '' }} aria-label="A skill's folder to upload" onChange={upload(false)} />
      <input ref={zipPick} type="file" hidden accept=".zip,application/zip" aria-label="A skill's .zip to upload" onChange={upload(true)} />
      <div className="field">
        <label htmlFor="skill-github">From GitHub</label>
        <input
          id="skill-github"
          className="input mono"
          value={github}
          placeholder="https://github.com/owner/repository/tree/main/folder"
          aria-describedby="skill-github-note"
          onChange={e => {
            setGithub(e.target.value)
            setFound(null)
          }}
          onKeyDown={enter(github.trim() ? { github: github.trim() } : null)}
        />
        <span id="skill-github-note" className="choice-note">
          A public repository, or a folder in it. Only its file list, SKILL.md, licence and scripts are read now; the rest
          is downloaded from the same commit when you add it.
        </span>
      </div>
      <button type="button" className="btn btn-small" disabled={busy || !github.trim()} onClick={() => read({ github: github.trim() })}>
        Read from GitHub
      </button>{' '}
      <button type="button" className="btn btn-small" onClick={onCancel}>
        Cancel
      </button>
      {found && (
        <div className="cmd-approval">
          <SkillShown skill={found.skill} />
          <ScriptsLeave id="skill-new-leave" skill={found.skill} texts={found.skill.script_texts} checked={unasked} onChange={setUnasked} />
          {replacing && (
            <p id="skill-new-replaces" className="choice-note">
              A skill named <span className="mono">{found.skill.name}</span> is kept already: this replaces it, and the roles that have it keep it.
            </p>
          )}
          <div className="change-actions">
            <button
              type="button"
              className="btn btn-small btn-primary"
              disabled={busy}
              aria-describedby={replacing ? 'skill-new-replaces' : undefined}
              onClick={() =>
                void act(async () => {
                  await onAdd(found.from, unasked, found.skill.sha256, replacing)
                  setFound(null)
                  setFolder('')
                  setGithub('')
                })
              }
            >
              {replacing ? 'Replace skill' : 'Add skill'}
            </button>
          </div>
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}


/** What the Tools page's part for skills is asked to do; each throws ApiError. */
export interface SkillActions {
  onPreviewSkill: (source: SkillSource) => Promise<SkillPreview>
  /** `replace`: in place of the one of its name (the roles that have it keep it). */
  onAddSkill: (source: SkillSource, scriptsRunUnasked: boolean, sha256: string, replace: boolean) => Promise<Skill>
  onSkillLeave: (skillId: string, scriptsRunUnasked: boolean) => Promise<void>
  onSkillOn: (skillId: string, on: boolean) => Promise<void>
  onDeleteSkill: (skillId: string) => Promise<void>
  onSkillRecord: () => Promise<SkillRecordRow[]>
  /** A skill given to a role or taken from it, or a group of tools it asks for given (0.1.0-ui: here, not on the role). */
  onPatchRole?: (roleId: string, change: RoleChange) => Promise<void>
}

interface Props extends SkillActions {
  skills: Skill[]
  roles: Role[]
  /** KOLONİ's own tools switched off on the Built-in tab: a skill that asks for one cannot run. */
  off: string[]
  /** The MCP servers switched off on the Servers tab: a skill that asks for one cannot run. */
  serversOff?: string[]
  /** Asked for from a role ("skills") or a spawn card ("skill:<name>", its row open). */
  picked?: string
  adding: boolean
  onAdding: (open: boolean) => void
}

/** K-skill-uyum: KOLONİ's own store of skills, a row each - on or off for every role, unfolded: what it asks, the roles it is given to, its SKILL.md, its scripts' leave, how it did. */
export function SkillsSection({ skills, roles, off, serversOff, picked, adding, onAdding, onPatchRole, ...actions }: Props) {
  const [open, setOpen] = useState<string | null>(picked?.startsWith('skill:') ? picked.slice(6) : null)
  const [rows, setRows] = useState<SkillRecordRow[]>([])
  const [error, setError] = useState<string | null>(null)
  // The skill whose delete is asked about: its row holds the question.
  const [deleting, setDeleting] = useState<string | null>(null)
  const confirm = useConfirm()
  const { onSkillRecord } = actions
  useEffect(() => {
    let latest = true
    // (No bars where it cannot be read: the unfolded row says why.)
    onSkillRecord().then(read => latest && setRows(read), () => {})
    return () => {
      latest = false
    }
  }, [onSkillRecord])
  const openId = skills.find(skill => skill.name === open)?.id
  useLayoutEffect(() => {
    if (picked?.startsWith('skill:') && openId) document.getElementById(`tools-skill-${openId}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [picked, openId])
  const act = (action: Promise<unknown>) => {
    setError(null)
    action.catch(err => setError(errorText(err)))
  }
  return (
    <>
      <p className="muted provider-note tools-lead">
        KOLONİ’s own store: a copy no agent writes.{' '}
        <Hint doc={GUIDE.skills}>
          A role is given one here, under its row; one you switch off is given to no role. Its agents are told each skill’s name and line, and read the
          whole of one when they need it.
        </Hint>
      </p>
      {adding && (
        <AddSkill
          onPreview={actions.onPreviewSkill}
          kept={skills.map(skill => skill.name)}
          onCancel={() => onAdding(false)}
          onAdd={async (source, unasked, sha256, replace) => {
            await actions.onAddSkill(source, unasked, sha256, replace)
          }}
        />
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {skills.length === 0 ? (
        <p className="muted hive-empty">No skill yet.</p>
      ) : (
        <ul className="tools-servers" aria-label="Skills">
          {skills.map(skill => {
            const shown = open === skill.name
            const given = roles.filter(role => role.skills.includes(skill.name))
            const agents = rows.filter(row => row.skill === skill.name).reduce((sum, row) => sum + row.agents, 0)
            return (
              <li key={skill.id}>
                <div className="tools-row">
                  <input type="checkbox" role="switch" className="switch" aria-label={`${skill.name} on`} checked={skill.enabled} onChange={() => act(actions.onSkillOn(skill.id, !skill.enabled))} />
                  <button
                    id={`tools-skill-${skill.id}`}
                    type="button"
                    className="tools-row-open"
                    aria-expanded={shown}
                    aria-controls={`tools-skill-box-${skill.id}`}
                    onClick={() => setOpen(shown ? null : skill.name)}
                  >
                    <span className="tools-row-text">
                      <span className="tools-row-name">{skill.name}</span>
                      <span className="muted tools-row-sub">{skill.description || 'It says nothing of itself.'}</span>
                    </span>
                    {/* As the mockup: where it is given, and where it cannot run there. */}
                    <span className="chips">
                      {given.length === 0 ? (
                        <span className="muted">no role</span>
                      ) : (
                        given.map(role => (
                          <span key={role.id} className="chip">
                            {cannotRun(skill, role, off, serversOff) && <span className="no">✗ </span>}
                            {role.name}
                          </span>
                        ))
                      )}
                    </span>
                    <span className="muted mono tools-row-use">{agents > 0 && `${count(agents, 'agent')} · 30 d`}</span>
                    <CaretDown size={13} aria-hidden className="tools-row-caret" />
                  </button>
                </div>
                <div id={`tools-skill-box-${skill.id}`} className="tools-skill-box" hidden={!shown}>
                  {shown && (
                    <>
                      <span className="muted mono tools-card-note">
                        {skill.version && `v${skill.version} · `}from {skill.source} · <Licence skill={skill} />
                      </span>
                      <SkillWindow skill={skill} roles={roles} off={off} serversOff={serversOff} onRecord={onSkillRecord} onPatchRole={onPatchRole} />
                      <SkillText skill={skill} />
                      <ScriptsLeave id={`skill-leave-${skill.id}`} skill={skill} checked={skill.scripts_run_unasked} onChange={on => act(actions.onSkillLeave(skill.id, on))} />
                      <div>
                        <button
                          type="button"
                          className="btn btn-small btn-danger"
                          onClick={() => {
                            setDeleting(skill.id)
                            confirm.ask(`Delete the skill ${skill.name}? Every role that has it loses it, and KOLONİ’s copy of it is removed.`, 'Delete skill', () => {
                              setOpen(was => (was === skill.name ? null : was))
                              act(actions.onDeleteSkill(skill.id))
                            }, 'Cancel')
                          }}
                        >
                          Delete skill {skill.name}
                        </button>
                      </div>
                      {deleting === skill.id && confirm.shown()}
                    </>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
