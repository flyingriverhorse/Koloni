import { titleOf } from '../agents/agentStatus'
import { api } from '../api/client'
import { canSwitch } from '../agents/chart'
import {
  TIERS,
  type Conversation,
  type Health,
  type Provider,
  type Role,
  type RoleModel,
  type Team,
  type Tier,
  type Tiers,
} from '../api/types'
import type { AppStore } from '../state/store'
import type { Cannot } from './ModelBanner'

/** What the store knows besides the rows: the roles, teams and providers, the tiers' models. */
export interface Known {
  roles: Role[]
  teams: Team[]
  providers: Provider[]
  tiers: Tiers | null
}

/** The tiers a job of the role may be given: any for a Lead that follows the message, a role's range where the Lead picks per job. */
function tiersOf(role: Role, chat: Conversation | null): Tier[] {
  if (role.builtin && role.name === 'Lead') return chat?.lead_auto ? TIERS : []
  // ("Never given a tier": a role with a model of its own, or one tier always - its row says where that runs.)
  if (role.tier !== null || role.provider_id) return []
  return TIERS.slice(TIERS.indexOf(role.tier_min ?? 'fast'), TIERS.indexOf(role.tier_max ?? 'strongest') + 1)
}

/**
 * The providers (ids) a chat would run on, for the top bar (sample A): the one the user chose for it, where each role
 * it may open would run now (`/roles/models`, the server's `would_run`) - so the default counts only where a role
 * falls back to it -, the model a lead that follows the message asks, and each tier's first model a job may be given.
 * And each such role that could not run where it would (`cannot_run`), as the bar says it.
 * A role it may open: as app/roles.py `closed` says with no role named in the message - where the Orchestrator decides,
 * any built-in role beside its picks; a team's lead as app/agent `_rows` opens one (beside another team, on).
 * shortcut: `closed`'s "Lead decides" rule against roles only in teams the Lead may not pick is not followed, nor a
 * recipe's step that holds the Orchestrator to its roles,
 * and a tier's first model is counted even where `pick` would pass over it (past its limit, down, its plan used);
 * follow them if a warning about such a provider is met.
 */
export function inUseBy(chat: Conversation | null, rows: RoleModel[], { roles, teams, providers, tiers }: Known) {
  const picked =
    chat && chat.teams_mode !== 'none' ? teams.filter(team => chat.teams.some(row => row.team_id === team.id)) : []
  const leads = picked.length > 1 ? picked.filter(team => team.lead_on).map(team => team.lead.name) : []
  const opens = (role: Role) =>
    !canSwitch(role) ||
    (role.enabled &&
      (leads.includes(role.name) ||
        picked.length === 0 ||
        (chat?.teams_mode === 'lead' && role.builtin) ||
        role.teams.some(id => picked.some(team => team.id === id))))
  const used = rows.flatMap(row =>
    roles.filter(role => role.name === row.role && opens(role)).map(role => ({ row, role })),
  )
  const tiered = ({ row, role }: (typeof used)[number]) =>
    tiersOf(role, chat).map(
      tier => tiers?.[tier].find(one => one.agents && row.pick_from.includes(one.provider_name))?.provider_name,
    )
  const names = used.flatMap(one => [one.row.provider_name, one.row.asks_how_hard?.provider_name, ...tiered(one)])
  // (A provider's name is its own: two are never named alike.)
  const ids = providers.filter(one => names.includes(one.name)).map(one => one.id)
  return {
    ids: [...new Set([...(chat?.provider_id ? [chat.provider_id] : []), ...ids])],
    cannot: used.flatMap(({ row }) => (row.cannot_run ? [{ who: titleOf(row.role, teams), why: row.cannot_run }] : [])),
  }
}

export const readHealth = (id: string | null) =>
  api.get<Health>(id ? `/health?provider_id=${encodeURIComponent(id)}` : '/health')

/** The top bar's: what /health says of each provider the open chat would run on, and the roles of it that cannot run (`inUseBy`). */
export async function inUseNow(
  get: () => AppStore,
  health: Health | null,
): Promise<{ readings: Health[]; cannot: Cannot[] }> {
  const chat = get().conv?.conversation ?? null
  try {
    // (Read with the page's first reading, they may not be here yet.)
    if (get().roles.length === 0) await get().loadRoles()
    if (get().providers.length === 0) await get().loadProviders()
    const [rows, tiers] = await Promise.all([
      get().roleModels(chat?.id ?? null),
      get()
        .tiers()
        .catch(() => null),
    ])
    const { ids, cannot } = inUseBy(chat, rows, { ...get(), tiers })
    // A reading that fails keeps the last one: one glitch neither quiets the bar nor shows it again after a dismissal.
    // (A provider never read before is left out until it is.)
    const last = (id: string) => get().inUse?.readings.find(one => one.provider_id === id) ?? null
    const read = (id: string) => (id === health?.provider_id ? health : readHealth(id).catch(() => last(id)))
    return { readings: (await Promise.all(ids.map(read))).filter(one => one !== null), cannot }
  } catch {
    // (No provider at all, or the roles not read: the one reading there is, as before.)
    return { readings: health ? [health] : [], cannot: [] }
  }
}
