import { withKey } from './client'

export const EVENT_TYPES = [
  'run.started',
  'run.updated',
  'run.finished',
  'run.thinking',
  'message.created',
  'message.completed',
  'message.delta',
  'message.sync',
  'tool_call.created',
  'tool_call.updated',
  'file_change.created',
  'file_change.updated',
  'conversation.updated',
  // A topic of the conversation was started, or named by the user.
  'topic.created',
  'topic.updated',
  'command.created',
  'command.updated',
  'command.output',
  'command.sync',
  // What an agent's CLI says of its context and plan while it works (89j): the latest, never stored.
  'agent.live',
  'allowed_commands.updated',
  // A web search or an HTTP request was put before the user, or decided; and what the
  // conversation sends out without asking changed.
  'web_request.updated',
  'allowed_web.updated',
  'agent.created',
  'agent.updated',
  'channel.created',
  'discussion.created',
  'discussion.updated',
  'discussion_post.created',
  // A room the user opened: itself (who is in it, how it stands, what it has spent), its
  // list of items and what is said in it. A post changes once: a question that is replied to.
  'room.created',
  'room.updated',
  'room_item.created',
  'room_item.updated',
  'room_post.created',
  'room_post.updated',
  'board.posted',
  'role_request.created',
  'role_request.resolved',
  'role.created',
  // A skill an agent asked to add: its card, decided, and the skill once added.
  'skill_request.created',
  'skill_request.resolved',
  'skill.created',
  'question.created',
  'question.updated',
  // The project's memory changed. It comes with an id from the conversation an agent wrote
  // it in and without one from anywhere else; either way the memory is read again.
  'memory.changed',
  // A task of the project's backlog was added, changed, decided on, started or ended its turn:
  // the backlog is read again (slice 52).
  'backlog.changed',
  // A trigger of the project was made, changed, paused, came due or saw its turn end:
  // the triggers are read again.
  'triggers.changed',
  // Who holds which file of the project now. From an agent of this conversation it comes
  // with an id, from one of another without: it says everything each time, so it is taken
  // as it arrives either way.
  'claims.changed',
  // An agent's working copy on its way into the project: asked about, taken, or not.
  'merge.updated',
  // A file the user attached (slice 85b): added, sent with its message or handed to an agent, or taken off.
  'attachment.created',
  'attachment.updated',
  'attachment.deleted',
  // Text from outside read like orders to an agent (93-A4): a warning, with the rule and where.
  'injection.warned',
  // A report or file put before the user (`show`, or one a command made): Outputs counts it.
  'view.shown',
  // A turn's "Add to Project notes?" offer was made or answered: the offers are read again.
  'notes.offered',
] as const

/**
 * Sent without an id and never stored. The browser reports the id of the last
 * event that had one for these too, so they are recognised by type, not by id.
 */
const TRANSIENT: ReadonlySet<string> = new Set([
  'run.thinking',
  'message.delta',
  'message.sync',
  'command.output',
  'command.sync',
  'agent.live',
  'triggers.changed',
  'backlog.changed',
  'claims.changed',
  'notes.offered',
  // (As claims: with an id for the chat's own, without for a site changed in another chat of the project or on its settings.)
  'allowed_web.updated',
])

type OnEvent = (id: number | null, type: string, payload: unknown) => void

/**
 * Subscribe to one conversation's events. On a dropped connection the source is
 * closed and `onLost` fires, so the caller can take a fresh snapshot and
 * resubscribe instead of trusting the browser's own partial replay.
 */
export function openEvents(
  conversationId: string,
  after: number,
  onEvent: OnEvent,
  onOpen: () => void,
  onLost: () => void,
): () => void {
  const source = new EventSource(withKey(`/api/conversations/${conversationId}/events?after=${after}`))
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, event => {
      const message = event as MessageEvent<string>
      const id = TRANSIENT.has(type) || !message.lastEventId ? null : Number(message.lastEventId)
      onEvent(id, type, JSON.parse(message.data))
    })
  }
  source.onopen = onOpen
  source.onerror = () => {
    source.close()
    onLost()
  }
  return () => source.close()
}
