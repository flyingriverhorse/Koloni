import type { KnowledgeState } from '../api/types'
import type { CellFill, CellTone } from '../shell/Cell'

/**
 * 0.1.10: how a source stands, as its card's cell says it - learning honey; a learning that failed, or a guide that may
 * be old, red-orange; learned green; never learned empty. Its words are the cell's label: the colour never says it alone.
 * Green says only that it was learned and no change is known (app/knowledge.py `stale`), never that it is fresh: a
 * repository, a folder or the code scan is not looked at again between learnings, a site or a topic only weekly, if asked.
 */
export function freshCell(state: KnowledgeState, code = false): { tone: CellTone; fill: CellFill; word: string } {
  if (state.learning) return { tone: 'honey', fill: 'full', word: code ? 'scanning' : 'learning' }
  if (state.failed) return { tone: 'warn', fill: 'full', word: 'its last learning failed' }
  if (!state.learned) return { tone: 'plain', fill: 'none', word: code ? 'not scanned' : 'not learned' }
  if (state.stale) return { tone: 'warn', fill: 'full', word: 'may be old' }
  return { tone: 'ok', fill: 'full', word: code ? 'scanned' : 'learned' }
}

/** A source whose guide may be old: counted on the sources' tab. */
export const mayBeOld = (state: KnowledgeState) => freshCell(state).word === 'may be old'
