import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { decidedSentence, openDecisions } from '../ready/decisionLog'
import { waitingCards } from './chatLine'
import { DecidedForYou } from './DecidedForYou'
import { decidedOf, decidedTasks, judgedCommands } from './waiting'

/**
 * The chat's one line of Decided for you (karar defteri): how many things were decided for you in it, not yet OK'd, and
 * how many wait for your word - and Ready for you, where its Decided for you says each, and its OK and Change are. Cards
 * that wait are answered in the chat as before. Nothing when nothing was decided for you: cards that wait alone have
 * their own count and cards (a watched chat's card is no "while you were away").
 * shortcut: "while you were away" - at Full auto the Orchestrator decides in a watched turn too (K-fullauto-sorma);
 * say "at Full auto" by the chat's level if the line is seen to mislead.
 */
export function DecidedLine({ conv }: { conv: ConvState | null }) {
  const backlog = useApp(s => s.backlog)
  if (!conv?.conversation.project_id) return null
  const decided =
    decidedOf(conv).length + decidedTasks(backlog, conv.conversation.id).length + judgedCommands(conv).length
  const waiting = waitingCards(conv)
  if (decided === 0) return null
  return (
    <p className="decided-line">
      <span>{decidedSentence(decided, waiting)}</span>{' '}
      {/* (at Not seen: what waits for your OK, one of any age, is there) */}
      <button type="button" className="link-btn" onClick={() => openDecisions(true)}>
        Open in Ready for you
      </button>
    </p>
  )
}

/**
 * Ready for you's list of a chat (the panel's This chat): its line - or, in a chat with no folder, which has no decision
 * log to say them in, Decided for you's own box, with its OK and Change.
 */
export function Decided({ state }: { state: ConvState }) {
  return state.conversation.project_id ? <DecidedLine conv={state} /> : <DecidedForYou state={state} />
}
