import { useState } from 'react'
import { errorText } from '../api/client'
import type { Story } from '../api/types'

const NEW = '__new__'

interface Props {
  id: string
  value: string | null
  stories: Story[]
  onChange: (storyId: string | null) => void
  /** A new story of this title, made now: its id. Throws ApiError. */
  onNew: (title: string) => Promise<string>
}

/** A task's story (0.1.8): none, one of the project's, or "New story…" - its title typed here, then Enter. */
export function StoryPicker({ id, value, stories, onChange, onNew }: Props) {
  const [naming, setNaming] = useState(false)
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const make = async () => {
    if (!title.trim()) return
    try {
      onChange(await onNew(title.trim()))
      setNaming(false)
      setTitle('')
      setError(null)
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="field">
      <label htmlFor={naming ? `${id}-new-story` : `${id}-story`}>{naming ? 'New story’s title' : 'Story'}</label>
      {naming ? (
        <input
          id={`${id}-new-story`}
          className="input"
          autoFocus
          maxLength={200}
          value={title}
          onChange={e => setTitle(e.target.value)}
          // (In a task's form: Enter makes the story, never sends the form; Esc goes back to the list.)
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void make()
            }
            if (e.key === 'Escape') {
              e.stopPropagation()
              setNaming(false)
            }
          }}
        />
      ) : (
        <select
          id={`${id}-story`}
          className="input"
          value={value ?? ''}
          onChange={e => (e.target.value === NEW ? setNaming(true) : onChange(e.target.value || null))}
        >
          <option value="">None</option>
          {stories.map(story => (
            <option key={story.id} value={story.id}>
              {story.title}
            </option>
          ))}
          <option value={NEW}>New story…</option>
        </select>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
