import type { Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/** What Fix it sends: a new message of the user's, by their click - nothing starts by itself. */
export const FIX_IT = (command: string) => `The tests KOLONİ ran at the end of the last turn failed: \`${command}\`. Fix what fails.`

/** A turn's "checked" message: what KOLONİ checked at its end (kanıtlı bitiş), drawn by `CheckedSection`. */
export const checkedOf = (state: ConvState, runId: string): Message | undefined => state.messages.find(m => m.run_id === runId && m.role === 'checked')
