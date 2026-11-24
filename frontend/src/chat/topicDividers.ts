import type { Message, Run, Story } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { titleOf } from '../topics/topics'
import { storyDivider } from './todo'

/** A topic's line in the chat, and the story whose topic it is (its 📓 opens the notebook: `TopicLine`). */
export interface Divider {
  text: string
  story: Story | null
}

// Where the topic changes: a line before the first message of a turn whose topic is not
// that of the turn before it. "New" only the first time the topic is seen.
export function topicDividers(state: ConvState, ordered: Message[], runs: Map<string, Run>, stories: Story[]) {
  const dividers = new Map<string, Divider>()
  const met = new Set<string>()
  let [turnBefore, topicBefore]: [string | null, string | null | undefined] = [null, undefined]
  for (const message of ordered) {
    if (message.run_id === turnBefore) continue
    turnBefore = message.run_id
    const topic = state.topics.find(t => t.id === runs.get(message.run_id)?.topic_id)
    // (0.1.8: a story's topic says its story - over the chat's first turn too.)
    const story = stories.find(one => one.id === topic?.story_id)
    if (topic && (topicBefore !== undefined || story) && topic.id !== topicBefore) {
      dividers.set(message.id, {
        text: story
          ? storyDivider(story)
          : `${met.has(topic.id) ? 'Continuing' : 'New topic'}: ${titleOf(state, topic)}`,
        story: story ?? null,
      })
    }
    if (topic) met.add(topic.id)
    topicBefore = topic?.id ?? null
  }
  return dividers
}
