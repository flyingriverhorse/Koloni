import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client'
import { Row } from './part'

type Mode = 'add' | 'ask'

/** The setting's words (the user's, 28 Nov). */
export const FROM_WORDS_WHY =
  'When you say in a chat how you want work done from now on, the Orchestrator can keep it in Your preferences, in every project. Add them, tell me: your own sentence is added at once - never the model’s wording - and the chat says so, with Undo. Ask me first: a card in the chat shows your words and the line, for Add or Not now.'

/** Settings › The app › Agents: New preferences from your words - Add them, tell me (the default) or Ask me first; kept as
 *  it is changed. Its row. */
export function useFromWords() {
  const [mode, setMode] = useState<Mode | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<{ mode: Mode }>('/preferences/from-words').then(
      read => setMode(read.mode),
      err => setError(errorText(err)),
    )
  }, [])
  async function change(value: Mode) {
    setError(null)
    try {
      setMode((await api.put<{ mode: Mode }>('/preferences/from-words', { mode: value })).mode)
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="settings-app-form">
      <Row
        label="New preferences from your words"
        htmlFor="from-words"
        why={FROM_WORDS_WHY}
        from={mode === undefined ? null : mode === 'add' ? 'usual' : 'here'}
      >
        <select
          id="from-words"
          className="input"
          value={mode ?? 'add'}
          disabled={mode === undefined}
          onChange={e => void change(e.target.value as Mode)}
        >
          <option value="add">Add them, tell me</option>
          <option value="ask">Ask me first</option>
        </select>
      </Row>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </div>
  )
}
