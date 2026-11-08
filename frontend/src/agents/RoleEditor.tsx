import { type LoadModels } from '../models/ModelNameInput'
import { type Takes } from '../models/levels'
import { modelName } from '../shell/modelName'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { type FormEvent, type ReactNode, useEffect, useId, useState } from 'react'
import { errorText } from '../api/client'
import { TIERS, type Provider, type Role, type RoleModel } from '../api/types'
import { kindName, mayDo } from './chart'
import { ModelCards, type Uses, USES, usesOf } from './ModelCards'
import type { Part } from './RolePanel'
import { PACKS, ROLE_TOOLS, TOOL_GROUPS } from './roleTools'
import { EMPTY, type Props, type RoleValues } from './AgentsPage'

/** Empty: no limit (null). A whole number above zero: that. Anything else is not sent (undefined). */
const limitOf = (text: string) => (text.trim() === '' ? null : /^[1-9]\d{0,14}$/.test(text.trim()) ? Number(text) : undefined)

interface EditorProps extends Omit<Props, 'roles' | 'providers' | 'onModels' | 'onRecord' | 'onRoleModels' | 'onFillAll' | 'onSaveFillAll' | 'teams' | 'onPatch' | 'onHistory' | 'onActivity' | 'teamActions' | 'categoryActions' | 'onOpenConversation' | 'onOpenTools' | 'skills' | 'onOpenSkills'> {
  onModels?: LoadModels
  role: Role | null
  /** The section it opens at (an Edit link's), and what puts it away unsaved. */
  at?: Part
  /** A new role's start: a copy of this one (decision 6). */
  copyOf?: Role
  onCancel?: () => void
  /** A new role's category, or its team, from where it is added. */
  kind?: string
  team?: string
  /** A team's lead (slice 63a): named after its team, and goes only with it. */
  teamLead?: boolean
  /** What its agents would run on now, as saved; undefined while read or where that failed. */
  runs?: RoleModel
  /** The reasoning levels its model (as saved) takes: see `Takes`. */
  takes?: Takes
  /** Its model's window as found, and where from; undefined while looked up, null where that failed. */
  found?: { window: number | null; from: string } | null
  providers: Provider[]
  onDone: () => void
}

/** One part of a role's form, under its heading. */
export function Section({ title, id: at, children }: { title: string; id?: string; children: ReactNode }) {
  const id = useId()
  return (
    <section id={at} className="role-section" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {children}
    </section>
  )
}

type SetValues = (patch: Partial<RoleValues>) => void

export function RoleEditor({ role, runs, takes: savedTakes, found: savedFound, providers, onModels, onFacts, onSave, onCreate, onDelete, onReset, onDone, onCancel, at, copyOf, kind = 'build', team, teamLead = false, categories = [], off }: EditorProps) {
  // A copy is filled from its role (decision 6), named "<name> copy"; its teams are not.
  const from = role ?? copyOf
  const [values, setValues] = useState<RoleValues>(
    from
      ? {
          name: role ? role.name : `${from.name} copy`,
          description: from.description,
          instructions: from.instructions,
          tools: from.tools,
          provider_id: from.provider_id,
          model_id: from.model_id,
          models: from.models,
          tier: from.tier,
          tier_min: from.tier_min,
          tier_max: from.tier_max,
          kind: from.kind,
          pick_from: from.pick_from,
          max_steps: from.max_steps,
          max_tokens: from.max_tokens,
          effort: from.effort,
          max_effort: from.max_effort,
          context_window: from.context_window,
          skills: from.skills,
          inside_cli: from.inside_cli,
          ...(!role && team && { teams: [team] }),
        }
      : // (Build, where the user has not deleted it; else the first category.)
        { ...EMPTY, kind: categories.some(one => one.key === kind) ? kind : (categories[0]?.key ?? kind), ...(team && { teams: [team] }) },
  )
  const isLead = !!role?.builtin && role.name === 'Lead'
  const uses = usesOf(values, isLead)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<RoleValues>) => setValues(v => ({ ...v, ...patch }))
  const [steps, setSteps] = useState(from?.max_steps ? String(from.max_steps) : '')
  const [tokens, setTokens] = useState(from?.max_tokens ? String(from.max_tokens) : '')
  const [windowText, setWindowText] = useState(from?.context_window ? String(from.context_window) : '')
  const maxSteps = limitOf(steps)
  const maxTokens = limitOf(tokens)
  const contextWindow = limitOf(windowText)
  const limitsOk = maxSteps !== undefined && maxTokens !== undefined && contextWindow !== undefined

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

  function submit(event: FormEvent) {
    event.preventDefault()
    if (maxSteps === undefined || maxTokens === undefined || contextWindow === undefined) return
    const sent = { ...values, max_steps: maxSteps, max_tokens: maxTokens, context_window: contextWindow }
    void run(async () => {
      if (role) await onSave(role.id, sent)
      else await onCreate(sent)
      onDone()
    })
  }

  function toggle(tool: string) {
    const has = values.tools.includes(tool)
    const next = has ? values.tools.filter(t => t !== tool) : [...values.tools, tool]
    set({ tools: ROLE_TOOLS.map(t => t.name).filter(name => next.includes(name)) })
  }

  const canCreate = values.name.trim() !== '' && values.tools.length > 0
  const pick = (one: Uses) => set(USES[one](isLead, providers))
  const pack = (tools: string[], on: boolean) => {
    const next = on ? [...values.tools, ...tools] : values.tools.filter(name => !tools.includes(name))
    set({ tools: ROLE_TOOLS.map(t => t.name).filter(name => next.includes(name)) })
  }
  const observer = !!role?.builtin && role.name === 'Observer'
  // The form opens at the section an Edit link names (decision 5).
  useEffect(() => {
    if (!at) return
    const part = document.getElementById(`role-part-${at}`)
    part?.scrollIntoView?.({ block: 'start' })
    part?.querySelector<HTMLElement>('input:not([readonly]), textarea, select')?.focus()
  }, [at])
  return (
    <form className="role-editor" onSubmit={submit}>
      <RoleWhat role={role} values={values} set={set} teamLead={teamLead} categories={categories} />
      <Section title="Model" id="role-part-model">
        {/* One card for each question; choosing which model clears the other choices' fields. */}
        <ModelCards
          role={role}
          from={from}
          values={values}
          set={set}
          uses={uses}
          pick={pick}
          isLead={isLead}
          observer={observer}
          teamLead={teamLead}
          providers={providers}
          onModels={onModels}
          onFacts={onFacts}
          runs={runs}
          savedTakes={savedTakes}
          savedFound={savedFound}
          windowText={windowText}
          setWindowText={setWindowText}
          contextWindow={contextWindow}
          at={at}
        />
      </Section>
      {!observer && (
        <Section title="It may" id="role-part-tools">
          <RoleTools values={values} pack={pack} toggle={toggle} at={at} off={off} />
        </Section>
      )}
      <RoleLimits
        at={at}
        lead={isLead}
        steps={steps}
        setSteps={setSteps}
        maxSteps={maxSteps}
        tokens={tokens}
        setTokens={setTokens}
        maxTokens={maxTokens}
      />
      <Section title="This role will">
        <RoleSummary
          values={values}
          teamLead={teamLead}
          categories={categories}
          uses={uses}
          providers={providers}
          observer={observer}
          maxSteps={maxSteps}
          maxTokens={maxTokens}
        />
      </Section>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="role-actions">
        {role ? (
          <button type="submit" className="btn btn-primary" disabled={busy || !limitsOk}>
            Save
          </button>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={busy || !canCreate || !limitsOk}>
            Create role
          </button>
        )}
        {onCancel && (
          <button type="button" className="btn" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        )}
        {role?.builtin && (
          <button type="button" className="btn" disabled={busy} onClick={() => void run(() => onReset(role.id))}>
            Reset to default
          </button>
        )}
        {role && !role.builtin && !teamLead && (
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={() => void run(() => onDelete(role.id))}
          >
            Delete role
          </button>
        )}
      </div>
    </form>
  )
}

/** What the role is: its name, line, category and instructions. */
function RoleWhat({ role, values, set, teamLead, categories }: {
  role: Role | null
  values: RoleValues
  set: SetValues
  teamLead: boolean
  categories: NonNullable<EditorProps['categories']>
}) {
  return (
    <div id="role-part-what" className="role-editor-what">
      {role?.created_by_agent && <span className="tag tag-accent">Created by an agent</span>}
      <div className="field">
        <label htmlFor="role-name">Name</label>
        <input
          id="role-name"
          className="input"
          value={values.name}
          // (A team's lead is named after its team: the team is renamed.)
          readOnly={role?.builtin || teamLead}
          onChange={e => set({ name: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="role-description">What it does</label>
        <input
          id="role-description"
          className="input"
          value={values.description}
          placeholder="One line"
          aria-describedby="role-description-note"
          onChange={e => set({ description: e.target.value })}
        />
        <span id="role-description-note" className="choice-note">
          The Orchestrator reads it to pick the role.
        </span>
      </div>
      {/* A team's lead is in no category: it is its team's. */}
      {!teamLead && (
        <div className="field">
          <label htmlFor="role-kind">Category</label>
          <select id="role-kind" className="input" value={values.kind} onChange={e => set({ kind: e.target.value })}>
            {!categories.some(one => one.key === values.kind) && <option value={values.kind}>{values.kind}</option>}
            {categories.map(one => (
              <option key={one.key} value={one.key}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="field">
        <label htmlFor="role-instructions">Instructions</label>
        <textarea
          id="role-instructions"
          className="input role-instructions"
          rows={6}
          value={values.instructions}
          placeholder="How an agent in this role should work"
          onChange={e => set({ instructions: e.target.value })}
        />
      </div>
    </div>
  )
}

/** What it may do: its tools, by pack or one by one. */
function RoleTools({ values, pack, toggle, at, off }: {
  values: RoleValues
  pack: (tools: string[], on: boolean) => void
  toggle: (tool: string) => void
  at: Part | undefined
  off: string[] | undefined
}) {
  return (
    <>
      <div className="role-packs">
        {PACKS.map(([title, line, tools]) => (
          <label key={title} className="role-pack">
            <input type="checkbox" checked={tools.every(name => values.tools.includes(name))} onChange={e => pack(tools, e.target.checked)} />
            <span>
              <b>{title}</b>
              <span className="choice-note">
                {line}
                {ROLE_TOOLS.some(tool => tool.asks && tools.includes(tool.name)) && ' · asks'}
              </span>
            </span>
          </label>
        ))}
      </div>
      <details className="more" open={at === 'tools'}>
        <summary>Pick tools one by one</summary>
        {TOOL_GROUPS.map(group => (
          <div key={group} className="tool-group">
            <h4>{group}</h4>
            {ROLE_TOOLS.filter(tool => tool.group === group).map(tool => (
              <label key={tool.name} className="tool-row" htmlFor={`tool-${tool.name}`}>
                <span>
                  <span className="mono">{tool.name}</span>
                  <span className="choice-note">
                    {tool.hint}
                    {off?.includes(tool.name) && ' · off on the Tools page'}
                  </span>
                </span>
                <input
                  id={`tool-${tool.name}`}
                  type="checkbox"
                  role="switch"
                  aria-label={tool.name}
                  checked={values.tools.includes(tool.name)}
                  onChange={() => toggle(tool.name)}
                />
              </label>
            ))}
          </div>
        ))}
      </details>
    </>
  )
}

function RoleLimits({ at, lead, steps, setSteps, maxSteps, tokens, setTokens, maxTokens }: {
  at: Part | undefined
  lead: boolean
  steps: string
  setSteps: (text: string) => void
  maxSteps: number | null | undefined
  tokens: string
  setTokens: (text: string) => void
  maxTokens: number | null | undefined
}) {
  return (
    <details id="role-part-limits" className="more role-limits" open={at === 'limits'}>
      <summary>
        Safety stops for one agent
        {(maxSteps || maxTokens) && <span className="muted"> · set</span>}
      </summary>
      <p className="choice-note">Stops one runaway agent of this role. Empty: {lead ? 'no step limit for the Orchestrator' : 'KOLONİ’s own step limit'}.</p>
      <div className="field">
        <label htmlFor="role-max-steps">At most this many steps</label>
        <input id="role-max-steps" className="input mono" inputMode="numeric" value={steps} placeholder="No limit" aria-invalid={maxSteps === undefined || undefined} aria-describedby="role-max-steps-note role-max-steps-more" onChange={e => setSteps(e.target.value)} />
        <span className="choice-note">
          <span id="role-max-steps-note">
            {maxSteps === undefined ? 'A whole number above zero, or empty for no limit. ' : ''}
            Model steps one agent of this role takes, added up over its task and each time it is told to go on, in this
            turn or a later one. A CLI working with its own tools (native) takes no steps KOLONİ can count: this limit does not hold it.
          </span>{' '}
          {/* What the limit does not hold is in sight, above; how it stops is behind ⓘ. */}
          <Hint doc={GUIDE.editingRole} id="role-max-steps-more">
            A change to the limit reaches an agent already open the next time it is told to go on. At the limit that agent stops as failed and says so; the agent that opened it hears it and goes on,
            and for the Orchestrator the work on the message ends. With nobody watching (a trigger’s message), what a sub-agent
            stopped there had changed is not kept. KOLONİ’s own step limit still holds. For a CLI session each message it
            writes is a step.
          </Hint>
        </span>
      </div>
      <div className="field">
        <label htmlFor="role-max-tokens">At most this many tokens</label>
        <input id="role-max-tokens" className="input mono" inputMode="numeric" value={tokens} placeholder="No limit" aria-invalid={maxTokens === undefined || undefined} aria-describedby="role-max-tokens-note role-max-tokens-more" onChange={e => setTokens(e.target.value)} />
        <span className="choice-note">
          <span id="role-max-tokens-note">
            {maxTokens === undefined ? 'A whole number above zero, or empty for no limit. ' : ''}
            Tokens one agent of this role sent and wrote, as its model reports them; checked before each model step, and
            stopped the same way. A model that reports nothing is not held by this. A CLI (a session, or its own tools)
            reports when it ends: it is held only before it starts again, not in the middle of its work.
          </span>{' '}
          <Hint doc={GUIDE.editingRole} id="role-max-tokens-more">
            Counted for the agent’s record on one message, over all it is given there: an agent carried on for a later
            message starts again from zero.
          </Hint>
        </span>
      </div>
    </details>
  )
}

function RoleSummary({ values, teamLead, categories, uses, providers, observer, maxSteps, maxTokens }: {
  values: RoleValues
  teamLead: boolean
  categories: NonNullable<EditorProps['categories']>
  uses: Uses
  providers: Provider[]
  observer: boolean
  maxSteps: number | null | undefined
  maxTokens: number | null | undefined
}) {
  const asks = ROLE_TOOLS.filter(tool => tool.asks && values.tools.includes(tool.name)).map(tool => tool.label.toLowerCase())
  const where =
    uses === 'pick'
      ? `the model the Orchestrator picks for each job, ${values.tier_min ?? TIERS[0]} to ${values.tier_max ?? TIERS[TIERS.length - 1]}`
      : uses === 'tier'
        ? `the first ${values.tier} model of your team guide`
        : uses === 'model'
          ? `${providers.find(p => p.id === values.provider_id)?.name ?? 'a provider'} · ${values.model_id ? modelName(values.model_id) : 'its default model'}`
          : 'the chat’s model'
  return (
    <div className="role-summary" aria-live="polite">
      <p>
        be called <b>{values.name.trim() || '…'}</b>
        {!teamLead && (
          <>
            , in <b>{kindName(categories, values.kind)}</b>
          </>
        )}
      </p>
      <p>
        run on <b>{where}</b>
      </p>
      <p>{observer ? 'answer one question about a report, with no tools' : values.tools.length ? `${mayDo(values.tools)}; nothing else` : 'do nothing yet: give it at least one tool'}</p>
      {!observer && <p>{asks.length ? `ask you first before it may ${asks.join(', ')}, as the chat’s permission level says` : 'never wait for your yes'}</p>}
      {(maxSteps || maxTokens) && (
        <p>
          stop one agent at {[maxSteps && `${maxSteps} steps`, maxTokens && `${maxTokens.toLocaleString('en-US')} tokens`].filter(Boolean).join(' or ')}
        </p>
      )}
    </div>
  )
}
