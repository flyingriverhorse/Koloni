import { X } from '@phosphor-icons/react'
import { type CSSProperties, type DragEvent, useEffect, useRef, useState } from 'react'
import type { Category, Colour, Role } from '../api/types'
import { fold } from '../shell/fold'
import { BUILT_IN_CATEGORIES, canSwitch, COLOURS, colourVar, draggedRole, FROM_LIBRARY, groupsOf } from './chart'

/** What changes the roles' categories (the store's methods, by their names). Each throws ApiError. */
export interface CategoryActions {
  /** Answers the new category's key. */
  addCategory: (name: string, colour: Colour) => Promise<string>
  changeCategory: (key: string, change: { name?: string; colour?: Colour }) => Promise<void>
  orderCategories: (order: string[]) => Promise<void>
  deleteCategory: (key: string) => Promise<void>
}

/** A role's face: its first letter on its category's colour (a mark: its name is always beside it). */
export function Avatar({ name, colour }: { name: string; colour: string }) {
  return (
    <span className="role-av" aria-hidden="true" style={{ '--c': colour } as CSSProperties}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
}

/** A category's name and colour, typed in place: Enter saves, Esc puts it away. */
export function CategoryForm({ name = '', colour = 'rose', button, onSave, onCancel }: { name?: string; colour?: Colour; button: string; onSave: (name: string, colour: Colour) => void; onCancel: () => void }) {
  const [text, setText] = useState(name)
  const [picked, pick] = useState<Colour>(colour)
  return (
    <form
      className="cat-form"
      onSubmit={e => {
        e.preventDefault()
        onSave(text.trim(), picked)
      }}
      onKeyDown={e => {
        if (e.key !== 'Escape') return
        // Its own: the panel around it is not closed by it.
        e.stopPropagation()
        onCancel()
      }}
    >
      <input className="input" aria-label="Category’s name" maxLength={40} autoFocus value={text} onChange={e => setText(e.target.value)} />
      <span role="radiogroup" aria-label="Category’s colour" className="cat-swatches">
        {COLOURS.map(one => (
          <input key={one} type="radio" name="category-colour" className="cat-swatch" aria-label={one} checked={picked === one} style={{ '--c': colourVar(one) } as CSSProperties} onChange={() => pick(one)} />
        ))}
      </span>
      <button type="submit" className="btn btn-small" disabled={!text.trim()}>
        {button}
      </button>
      <button type="button" className="btn btn-small" onClick={onCancel}>
        Cancel
      </button>
    </form>
  )
}

type Filter = 'all' | 'loose' | 'off'
const teamsText = (n: number) => (n === 0 ? 'no team' : n === 1 ? '1 team' : `${n} teams`)

interface Props {
  /** Every role the library shows: not the Lead, not a team's lead. */
  roles: Role[]
  categories: Category[]
  selected: string | null
  onOpen: (roleId: string) => void
  onSwitch: (role: Role, on: boolean) => void
  /** A role dropped on a category's heading: put in it. */
  onKind: (role: Role, key: string) => void
  /** A drag from here begins (the role) or ends (null): the open team shows where it may land. */
  onDrag: (role: Role | null) => void
  actions?: CategoryActions
  act: (work: Promise<void> | undefined) => void
  /** A narrow window's drawer (slice 63b): open over the teams, and what closes it. */
  open: boolean
  onClose: () => void
}

/** The roles (slice 63b): each once, by category, folded or not; found by name, in no team or off; dragged into a team's stage. */
export function RoleLibrary({ roles, categories, selected, onOpen, onSwitch, onKind, onDrag, actions, act, open, onClose }: Props) {
  const [words, setWords] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [shut, setShut] = useState<Set<string>>(new Set())
  const [menu, setMenu] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const search = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (open) search.current?.focus()
  }, [open])
  const wanted = fold(words.trim())
  const loose = roles.filter(role => role.teams.length === 0)
  const off = roles.filter(role => !role.enabled)
  const shown = (filter === 'loose' ? loose : filter === 'off' ? off : roles).filter(role => !wanted || fold(`${role.name} ${role.description}`).includes(wanted))
  // Looking for some, a category with none of them is left out; else every one stands, an empty one too.
  const looking = !!wanted || filter !== 'all'
  const groups = groupsOf(shown, categories).filter(group => !looking || group.roles.length > 0)
  const all = groupsOf(roles, categories)
  const byId = new Map(roles.map(role => [role.id, role]))
  const toggle = (key: string) => setShut(was => (was.has(key) ? new Set([...was].filter(one => one !== key)) : new Set([...was, key])))
  const move = (at: number, by: number) => {
    const order = categories.map(one => one.key)
    ;[order[at], order[at + by]] = [order[at + by], order[at]]
    act(actions?.orderCategories(order))
  }
  const drop = (key: string) => (event: DragEvent) => {
    const role = byId.get(draggedRole(event)[1])
    if (!role) return
    event.preventDefault()
    if (role.kind !== key) onKind(role, key)
  }
  return (
    // A narrow window's drawer closes on Esc, and is gone into when opened (its search).
    <aside className={`role-lib${open ? ' role-lib-open' : ''}`} aria-label="Roles" onKeyDown={e => open && e.key === 'Escape' && onClose()}>
      {/* 0.1.0-ui: its head and filter stay at the top while its list scrolls under them. */}
      <div className="role-lib-top">
        <div className="role-lib-head">
          <h3>Roles</h3>
          <span className="muted">
            {roles.length}
            {off.length > 0 && ` · ${off.length} off`}
          </span>
          <button type="button" className="icon-btn role-lib-close" aria-label="Close the roles" onClick={onClose}>
            <X size={13} />
          </button>
        </div>
        <input
          ref={search}
          type="search"
          className="input role-lib-search"
          placeholder="Filter roles…"
          aria-label="Search roles"
          value={words}
          onChange={e => setWords(e.target.value)}
        />
        <div role="group" aria-label="Show" className="agents-pills role-lib-filters">
          {(
            [
              ['all', 'All'],
              ['loose', `In no team · ${loose.length}`],
              ['off', `Off · ${off.length}`],
            ] as const
          ).map(([one, title]) => (
            <button key={one} type="button" className="agents-pill" aria-pressed={filter === one} onClick={() => setFilter(one)}>
              {title}
            </button>
          ))}
        </div>
      </div>
      {groups.map(group => {
        const at = categories.findIndex(one => one.key === group.key)
        const every = all.find(one => one.key === group.key)?.roles ?? []
        const offHere = every.filter(role => !role.enabled).length
        const folded = shut.has(group.key) && !looking
        return (
          // (Only a category of the list takes a role dropped on it: a kind no category has is no place to put one.)
          <section
            key={group.key}
            className="cat"
            aria-label={group.name}
            style={{ '--c': colourVar(group.colour) } as CSSProperties}
            onDragOver={group.listed ? e => e.preventDefault() : undefined}
            onDrop={group.listed ? drop(group.key) : undefined}
          >
            {editing === group.key ? (
              <CategoryForm
                name={group.name}
                colour={group.colour}
                button="Save"
                onSave={(name, colour) => act(actions?.changeCategory(group.key, { name, colour }).then(() => setEditing(null)))}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <h4 className="cat-h">
                <button type="button" className="cat-fold" aria-expanded={!folded} onClick={() => toggle(group.key)}>
                  <span className="cat-dot" aria-hidden="true" />
                  {group.name}
                  <span className="muted">
                    {every.length}
                    {offHere > 0 && ` · ${offHere} off`}
                  </span>
                </button>
                {group.listed && (
                  <button type="button" className="icon-btn cat-more" aria-label={`${group.name}: more`} aria-expanded={menu === group.key} onClick={() => setMenu(menu === group.key ? null : group.key)}>
                    ⋯
                  </button>
                )}
              </h4>
            )}
            {/* What its key does beyond a label: app/agent.py tells a check role the findings' format. */}
            {group.key === 'check' && <p className="muted cat-note">Roles here report findings</p>}
            {menu === group.key && (
              <div
                className="cat-menu"
                role="group"
                aria-label={`${group.name}'s menu`}
                onKeyDown={e => {
                  if (e.key !== 'Escape') return
                  // Its own: the drawer around it is not closed by it.
                  e.stopPropagation()
                  setMenu(null)
                }}
              >
                {(
                  [
                    ['Rename…', false, () => setEditing(group.key)],
                    ['Move up', at === 0, () => move(at, -1)],
                    ['Move down', at === categories.length - 1, () => move(at, 1)],
                    ['Fold all others', false, () => setShut(new Set(all.map(one => one.key).filter(key => key !== group.key)))],
                    // Only an empty one of the user's goes: no role is ever left without a category, and KOLONİ's four stay.
                    BUILT_IN_CATEGORIES.includes(group.key)
                      ? ['Delete — one of KOLONİ’s four: rename it instead', true, () => undefined]
                      : [every.length ? `Delete — move its ${every.length === 1 ? 'role' : `${every.length} roles`} first` : 'Delete', every.length > 0, () => act(actions?.deleteCategory(group.key))],
                  ] satisfies [string, boolean, () => void][]
                ).map(([title, disabled, run]) => (
                  <button
                    key={title}
                    type="button"
                    className="cat-menu-item"
                    disabled={disabled}
                    onClick={() => {
                      setMenu(null)
                      run()
                    }}
                  >
                    {title}
                  </button>
                ))}
              </div>
            )}
            {!folded &&
              group.roles.map(role => (
                <div
                  key={role.id}
                  className={`lib-row${role.enabled ? '' : ' lib-row-off'}${selected === role.id ? ' lib-row-chosen' : ''}`}
                  draggable
                  onDragStart={e => {
                    e.dataTransfer.setData('text/plain', `${FROM_LIBRARY} ${role.id}`)
                    // (After the drag has begun: changing the page under it inside dragstart stalls Chrome's drag.)
                    setTimeout(() => onDrag(role))
                  }}
                  onDragEnd={() => onDrag(null)}
                >
                  <span className="lib-grip" aria-hidden="true">
                    ⋮⋮
                  </span>
                  <button type="button" className="lib-row-open" aria-current={selected === role.id || undefined} onClick={() => onOpen(role.id)}>
                    <Avatar name={role.name} colour={colourVar(group.colour)} />
                    <span className="lib-row-name">{role.name}</span>
                    <span className={`lib-uses${role.teams.length ? '' : ' lib-uses-none'}`}>{teamsText(role.teams.length)}</span>
                  </button>
                  {/* The Lead, the Planner and the Observer are always there: no switch. */}
                  {canSwitch(role) && <input type="checkbox" role="switch" className="model-agents lib-switch" aria-label={`${role.name} on`} checked={role.enabled} onChange={e => onSwitch(role, e.target.checked)} />}
                </div>
              ))}
          </section>
        )
      })}
      {groups.length === 0 && <p className="muted provider-note">No role is like that.</p>}
      {adding ? (
        <CategoryForm button="Add" onSave={(name, colour) => act(actions?.addCategory(name, colour).then(() => setAdding(false)))} onCancel={() => setAdding(false)} />
      ) : (
        <button type="button" className="agents-add role-lib-new" onClick={() => setAdding(true)}>
          + New category
        </button>
      )}
      <p className="muted role-lib-foot">Drag a role into a team’s stage, or onto a category. Click one to open it. A category is a label to find roles by: it changes no team’s stages.</p>
    </aside>
  )
}
