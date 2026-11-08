import type { FileChange } from '../api/types'

/**
 * A command that has the user's yes - to it, or given before (a rule, the level) - and has not
 * started: the yes is kept, and carried out when its agent has a place among the agents at work
 * and where it runs is ready. In words that stay true for both waits. It is not withdrawn - only
 * Stop ends it, with the turn.
 */
export const WAITS_FOR_A_PLACE =
  'it starts once its agent has a place among the agents at work. The approval cannot be taken back; Stop ends the work.'

/**
 * The same for a change, in words that stay true from the yes until the change is made: a CLI
 * that writes with a tool of its own has its place a moment before its write is seen.
 */
export const MADE_WITH_A_PLACE =
  'it is made once its agent has a place among the agents at work. The approval cannot be taken back; Stop ends the work.'

/**
 * A change that never reached the project though nobody said no to it. The record does not say
 * which of the two it was, so both are said.
 */
export const NEVER_MADE =
  'Discarded — never made in the project: its working copy was thrown away, or you approved it and the work ended before it was made'

/**
 * A change an agent made in its copy to a file the project changed too. What the project got is
 * not this change but the one that puts the two sides together: a record of its own.
 */
export const TAKEN_TOGETHER =
  'Merged — the project changed this file too: what it got is one change that puts the two together, and that one is the change to revert'

export const CHANGE_LABEL: Record<FileChange['status'], [text: string, tag: string]> = {
  proposed: ['Waits for you', 'tag tag-warn'],
  // The user said yes; it is made when its agent has a place among the agents at work.
  approved: ['Approved — not made yet', 'tag'],
  // Made in the agent's working copy: the project does not have it (yet).
  in_copy: ['In its copy', 'tag'],
  applied: ['Applied', 'tag tag-ok'],
  rejected: ['Rejected', 'tag'],
  // Never in the project, and nobody said no: thrown away with its working copy (Stop, or a
  // turn nobody watched), or approved and the turn ended before it was made.
  discarded: ['Discarded', 'tag'],
  reverted: ['Reverted', 'tag'],
  conflict: ['Conflict', 'tag tag-del'],
  failed: ['Not written', 'tag tag-del'],
  // Made in the agent's copy to a file the project changed too (`TAKEN_TOGETHER`).
  merged: ['Merged', 'tag'],
}
