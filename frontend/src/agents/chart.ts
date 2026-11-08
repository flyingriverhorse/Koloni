import type { DragEvent } from 'react'
import { type Category, type Colour, type Provider, type Role, type RoleModel, type RolesActivity, TIERS } from '../api/types'
import { modelName } from '../shell/modelName'

/**
 * What stands in the way of a role's agent where it runs now, in the server's words (`/roles/models`, B-89): as any
 * agent, and - asked for - as a recipe's step or a room's member. Said before a run, where it was only said in one.
 */
export function cannotOf(row: RoleModel | undefined, ...as: ('step' | 'room')[]): string[] {
  if (!row) return []
  return [
    row.cannot_run && `It would not run there now: ${row.cannot_run}`,
    as.includes('step') && row.cannot_step && `Not as a recipe’s step: ${row.cannot_step}`,
    as.includes('room') && row.cannot_room && `Not in a room: ${row.cannot_room}`,
  ].filter((said): said is string => !!said)
}

/** The palette a category's colour is picked from (app.schemas.Colour, slice 63b): each theme draws it its own way. */
export const COLOURS: Colour[] = ['violet', 'amber', 'green', 'blue', 'rose', 'teal', 'brown', 'olive']
export const colourVar = (colour: Colour) => `var(--cat-${colour})`
/** KOLONİ's four categories (app/api/categories.py): renamed and recoloured, never deleted. */
export const BUILT_IN_CATEGORIES = ['plan', 'build', 'check', 'write']
/** A role's colour and its category's name ("brown" and the key itself for a kind no category has). */
export const kindColour = (categories: Category[], kind: string) => colourVar(categories.find(one => one.key === kind)?.colour ?? 'brown')
export const kindName = (categories: Category[], kind: string) => categories.find(one => one.key === kind)?.name ?? kind

/** The library's groups: the categories in their order, then any kind a role has that no category is (shown, not changed). */
export interface CategoryGroup {
  key: string
  name: string
  colour: Colour
  roles: Role[]
  /** A category of the list (false: a kind no category has). */
  listed: boolean
}
export function groupsOf(roles: Role[], categories: Category[]): CategoryGroup[] {
  const keys = new Set(categories.map(one => one.key))
  const loose = [...new Set(roles.map(role => role.kind).filter(kind => !keys.has(kind)))]
  return [
    ...categories.map(one => ({ ...one, roles: roles.filter(role => role.kind === one.key), listed: true })),
    ...loose.map(kind => ({ key: kind, name: kind, colour: 'brown' as const, roles: roles.filter(role => role.kind === kind), listed: false })),
  ]
}

/** What a drag of a role from the library carries: read by a stage and a category's heading. */
export const FROM_LIBRARY = 'library'
/** Where a dragged role is from and its id: "<from> <role id>" (a team's id, or the library). */
export const draggedRole = (event: DragEvent) => event.dataTransfer.getData('text/plain').split(' ')

const isBuiltin = (role: Role, name: string) => role.builtin && role.name === name
/** The roles drawn under the Lead: all but the Lead itself (the Observer too: KOLONİ asks it, and its model is set here). */
export const drawn = (roles: Role[]) => roles.filter(role => !isBuiltin(role, 'Lead'))
/** The Lead, the Planner and the Observer are always there: no switch. */
export const canSwitch = (role: Role) => !role.builtin || !['Lead', 'Planner', 'Observer'].includes(role.name)

/** Which model a role uses, in a few words (mockup B), wherever it is said: "Orchestrator · fast–strongest",
 *  "Always balanced", "Claude Code · opus", "As the chat". */
export function ruleText(role: Pick<Role, 'provider_id' | 'model_id' | 'tier' | 'tier_min' | 'tier_max'>, providers: Pick<Provider, 'id' | 'name'>[], isLead = false): string {
  if (role.provider_id) return `${providers.find(p => p.id === role.provider_id)?.name ?? 'a provider'} · ${role.model_id ? modelName(role.model_id) : 'its default'}`
  // (The Lead's own "none" is the conversation's model.)
  if (role.tier === 'conversation' || (!role.tier && isLead)) return 'As the chat'
  if (role.tier) return `Always ${role.tier}`
  const [from, to] = [role.tier_min ?? TIERS[0], role.tier_max ?? TIERS[TIERS.length - 1]]
  return from === to ? `Always ${from}` : `Orchestrator · ${from}–${to}`
}

/** A card's second line: whose rule it is, where its last agent ran, or that none has. */
export function lastLine(role: Role, last: RolesActivity['last'][string] | undefined): string {
  if (role.tier || role.provider_id) return 'your rule'
  if (!last) return 'Not used yet'
  const where = last.model_id ? modelName(last.model_id) : (last.provider_name ?? 'model unknown')
  return `Last: ${where}${last.tier ? `, ${last.tier}` : ''}`
}

/** What an agent of these tools may do, in plain words; the conversation's permission level says whether it asks. */
export function mayDo(tools: string[]): string {
  const has = (...names: string[]) => names.some(name => tools.includes(name))
  return (
    [
      has('read_file', 'list_dir', 'search') && 'read and search',
      has('write_file', 'edit_file') && 'write files',
      has('run_command') && 'run commands',
      has('web_search', 'http_request') && 'search the web',
      has('spawn_agent') && 'hand work to others',
    ]
      .filter(Boolean)
      .join(' · ') || 'nothing but talk'
  )
}
