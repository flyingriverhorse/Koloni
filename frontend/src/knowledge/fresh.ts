import type { KnowledgeState } from '../api/types'
import type { CellFill, CellTone } from '../shell/Cell'

/**
 * 0.1.10: how fresh a source is, as its card's cell says it - learning honey; a learning that failed, or a guide that may
 * be old, red-orange; learned green; never learned empty. Its words are the cell's label: the colour never says it alone.
 */
export function freshCell(state: KnowledgeState, code = false): { tone: CellTone; fill: CellFill; word: string } {
  if (state.learning) return { tone: 'honey', fill: 'full', word: code ? 'scanning' : 'learning' }
  if (state.failed) return { tone: 'warn', fill: 'full', word: 'its last learning failed' }
  if (!state.learned) return { tone: 'plain', fill: 'none', word: code ? 'not scanned' : 'not learned' }
  if (state.stale) return { tone: 'warn', fill: 'full', word: 'may be old' }
  return { tone: 'ok', fill: 'full', word: 'fresh' }
}

/** A source whose guide may be old: counted on the sources' tab. */
export const mayBeOld = (state: KnowledgeState) => freshCell(state).word === 'may be old'
