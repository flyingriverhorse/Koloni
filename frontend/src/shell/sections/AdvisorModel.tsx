import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client'
import type { AdvisorOut } from '../../api/types'
import { Row } from './part'

/** The Advisor model's words (the plan's, 0.1.11). */
export const ADVISOR_WHY =
  "A model the Orchestrator may ask for advice. It sees the Orchestrator's summary and the turn's recent steps, masked."

/** A choice's value in the list: its provider and its model. */
const keyOf = (provider: string, model: string) => `${provider}\n${model}`

/** Settings › The app › Agents (0.1.11): whom the Orchestrator's ask_advisor asks, in every project - another provider's
 *  model than the Orchestrator's unless one is chosen; kept as it is changed. Its row. */
export function useAdvisorModel() {
  const [read, setRead] = useState<AdvisorOut | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<AdvisorOut>('/advisor').then(setRead, err => setError(errorText(err)))
  }, [])
  async function change(value: string) {
    const [provider_id, model_id] = value ? value.split('\n') : [null, null]
    setError(null)
    try {
      setRead(await api.put<AdvisorOut>('/advisor', { provider_id, model_id }))
    } catch (err) {
      setError(errorText(err))
    }
  }
  const choices = read?.choices ?? []
  const chosen = read?.provider_id && read.model_id ? keyOf(read.provider_id, read.model_id) : ''
  const listed = choices.some(one => keyOf(one.provider_id, one.model_id) === chosen)
  return (
    <div className="settings-app-form">
      <Row
        label="Advisor model"
        htmlFor="advisor-model"
        why={ADVISOR_WHY}
        warn={
          chosen &&
          !listed && (
            <span className="choice-note">
              Your choice, {read?.model_id}, cannot be asked now, so another provider’s model is asked.
            </span>
          )
        }
        from={read === undefined ? null : chosen ? 'here' : 'usual'}
      >
        <select
          id="advisor-model"
          className="input"
          value={chosen}
          disabled={read === undefined}
          onChange={e => void change(e.target.value)}
        >
          <option value="">Another provider’s than the Orchestrator’s</option>
          {choices.map(one => (
            <option key={keyOf(one.provider_id, one.model_id)} value={keyOf(one.provider_id, one.model_id)}>
              {one.provider_name} · {one.model_id} ({one.tier})
            </option>
          ))}
          {chosen && !listed && <option value={chosen}>{read?.model_id} (cannot be asked now)</option>}
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
