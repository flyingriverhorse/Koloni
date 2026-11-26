import { type KeyboardEvent, type RefObject, useState } from 'react'
import type { OwnCommand, Role } from '../api/types'
import { fold } from '../shell/fold'
import { useApp } from '../state/store'

/**
 * A command of the `/` menu (slice 46): the keyboard's way to a button that is there already.
 * A role's does nothing when chosen: it becomes the chip, and the task is written after it.
 */
export interface SlashCommand {
  name: string
  what: string
  /** Why it cannot be chosen now; null while it can. */
  off: string | null
  /** Done when chosen. */
  run?: () => void
  /** Or the buttons under the box it presses, in turn. */
  press?: string[]
  /** Or the text it puts in the box (the user's own, slice 53). */
  fill?: string
  /** Named in full with what follows it ("/test-yaz login form"): it alone is meant. */
  called?: boolean
}

/** The commands' names: a role of one of these names is left out, not shown as a second one. */
const COMMANDS = ['new', 'stop', 'model', 'mode', 'plan', 'compare']

/** What the box's commands act on: the Composer's state and its parts that are there or not. */
export interface SlashOn {
  draft: string
  setDraft: (text: string) => void
  compact: boolean
  running: boolean
  onStop: () => void
  /** The next message starts a new topic anyway (`noTopic`), or already will (`fresh`). */
  noTopic: boolean
  fresh: boolean
  startTopic: () => void
  model: boolean
  compare: boolean
  planFirst: boolean
  onPlanFirst?: (on: boolean) => void
  /** Where the buttons it presses are. */
  row: RefObject<HTMLElement | null>
}

/** The built-in commands, each off with why where it cannot be chosen now (`closed`: the chat is closed). */
function builtIn(on: SlashOn, closed: string | null): SlashCommand[] {
  return [
    {
      name: 'new',
      what: 'Start a new topic with the next message',
      off: on.noTopic || on.fresh ? 'it starts one anyway' : null,
      run: on.startTopic,
    },
    { name: 'stop', what: 'Stop the work in progress', off: on.running ? null : 'nothing is at work', run: on.onStop },
    {
      name: 'model',
      what: 'Choose this conversation’s model',
      off: closed ?? (on.model ? null : 'no model to choose yet'),
      press: ['.model-picker-button'],
    },
    // Only the chooser: a higher level is still the user's own pick, sent from this page.
    { name: 'mode', what: 'Choose the permission level', off: closed, press: ['.composer-level'] },
    {
      name: 'plan',
      what: `Switch Plan first ${on.planFirst ? 'off' : 'on'}`,
      off: on.onPlanFirst ? null : 'there is no conversation to set it on',
      run: () => on.onPlanFirst?.(!on.planFirst),
    },
    {
      name: 'compare',
      what: 'Send the message to two models side by side',
      off: closed ?? (on.compare ? null : 'there is no model to compare with yet'),
      press: ['.composer-more > button', '.composer-compare button'],
    },
  ]
}

/** The user's own command (slice 53): its text filled in with what follows its name; a role's, as that role's chip. */
function ownCommand(c: OwnCommand, draft: string, roles: Role[]): SlashCommand {
  // Its name, then a space or a new line: what follows may take more lines.
  const called =
    fold(draft.slice(0, c.name.length + 1)) === fold(`/${c.name}`) && /\s/.test(draft.charAt(c.name.length + 1))
  const typed = called ? draft.slice(c.name.length + 2).trim() : ''
  const line = c.template.split('\n')[0]
  // (split/join, not replace: a `$&` typed stays as it was typed.)
  const filled = c.template.includes('{args}')
    ? c.template.split('{args}').join(typed)
    : [c.template, typed].filter(Boolean).join(' ')
  // As the role's chip; a role gone since leaves the text, not a "/Ghost" sent as words.
  const chip = c.role === null ? undefined : roles.find(r => fold(r.name) === fold(c.role!))
  return {
    name: c.name,
    what: c.description || (line.length > 80 ? `${line.slice(0, 79)}…` : line),
    off: null,
    fill: chip ? `/${chip.name} ${filled}` : filled,
    called,
  }
}

/** A role named at the start ("/coder fix it", any case), the longest name first: none where Esc left it as text (`kept`). */
function roleOf(draft: string, kept: string | null, roles: Role[]): Role | null {
  if (kept && draft.startsWith(kept)) return null
  return (
    [...roles]
      .sort((a, b) => b.name.length - a.name.length)
      .find(r => fold(draft.slice(0, r.name.length + 2)) === fold(`/${r.name} `)) ?? null
  )
}

/** What the menu is asked for: the box holds one line that starts with `/`, or names an own command in full; null: no menu. */
function wantedOf(draft: string, role: Role | null, shut: string | null, commands: SlashCommand[]): string | null {
  const asks = /^\/[^\n]*$/.test(draft) || commands.some(c => c.called)
  return !role && shut !== draft && asks ? fold(draft.slice(1)) : null
}

/**
 * The `/` menu (slice 46): open while the box holds one line that starts with `/` and names a command, until Esc or the
 * focus leaves - closed then till something is written. Its role's chip, and the task after it.
 */
export function useSlash(on: SlashOn) {
  const { draft, setDraft } = on
  // (Not the Lead: the message goes to it anyway.)
  const roles = useApp(s => s.roles).filter(r => r.name !== 'Lead' && !COMMANDS.includes(fold(r.name)))
  // The user's own (slice 53), after the built-ins.
  // One named as a role made after it is hidden: the role's chip wins (the server refuses the name while the role is there).
  const own = useApp(s => s.ownCommands).filter(c => !roles.some(r => fold(r.name) === fold(c.name)))
  // What Esc left as it was written ("/tester"): text, not a chip, while the box starts with it.
  const [kept, setKept] = useState<string | null>(null)
  const role = roleOf(draft, kept, roles)
  const head = role ? draft.slice(0, role.name.length + 2) : ''
  const [shut, setShut] = useState<string | null>(null)
  const [at, setAt] = useState(0)
  // shortcut: pressed by class, a rename in ModelPicker breaks /model silently; upgrade to props if it bites.
  // shortcut: closed, the row under the box is hidden and so is what these open; upgrade by opening the chat first if asked.
  const closed = on.compact ? 'open the chat for this' : null
  const commands: SlashCommand[] = [
    ...builtIn(on, closed),
    ...roles.map(r => ({ name: r.name, what: `Ask the Orchestrator to hand a task to the ${r.name} role`, off: null })),
    ...own.map(c => ownCommand(c, draft, roles)),
  ]
  // shortcut: while an own command's text takes more lines, the arrows move in the menu, not between the lines; Esc frees them.
  const wanted = wantedOf(draft, role, shut, commands)
  // Named in full first ("/mode" is not "/model"), then those it starts, then those holding it.
  const rank = (command: SlashCommand) =>
    command.called || fold(command.name) === wanted ? 0 : fold(command.name).startsWith(wanted ?? '') ? 1 : 2
  const shown =
    wanted === null
      ? []
      : commands.filter(c => c.called || fold(c.name).includes(wanted)).sort((a, b) => rank(a) - rank(b))
  const active = Math.min(at, shown.length - 1)

  function choose(command: SlashCommand) {
    if (command.off) return
    setAt(0)
    setKept(null)
    if (command.fill !== undefined) return setDraft(command.fill)
    if (!command.run && !command.press) return setDraft(`/${command.name} `)
    setDraft('')
    command.run?.()
    // What the button does, unless what it opens is open already.
    for (const selector of command.press ?? []) {
      const button = on.row.current?.querySelector<HTMLElement>(selector)
      if (button?.getAttribute('aria-expanded') !== 'true') button?.click()
    }
  }

  /** The open menu's keys: the arrows move in it, Enter (or Tab) chooses, Esc closes it. True where the key was its. */
  function menuKey(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setAt((active + (event.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length)
      return true
    }
    // (Tab on one that is off is not taken: the focus moves on.)
    if (!event.shiftKey && (event.key === 'Enter' || (event.key === 'Tab' && !shown[active].off))) {
      event.preventDefault()
      choose(shown[active])
      return true
    }
    if (event.key === 'Escape') {
      event.stopPropagation() // the menu's: the chat stays open
      setKept(draft)
      setShut(draft)
      return true
    }
    return false
  }

  return {
    role,
    head,
    text: draft.slice(head.length),
    shown,
    menu: shown.length > 0,
    active,
    choose,
    menuKey,
    setShut,
    setAt,
  }
}
