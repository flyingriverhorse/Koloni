import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client'
import type { JudgeOut } from '../../api/types'
import { GUIDE } from '../guide'
import { Row } from './part'

const JUDGE_WHY =
  'For every project: the model Full auto’s judge asks whether a command looks risky, and Check what I said first whether your words cover one. It is sent your words and the command, with the secrets KOLONİ knows masked, and answers with no tools - one request for each such command, on your plan or your bill; Usage shows it under KOLONİ itself.'

/** A choice's value in the list: its provider and its model. */
const keyOf = (provider: string, model: string) => `${provider}\n${model}`

/** Under the Judge model: what is asked now where it is not plainly the one shown. */
function JudgeNotes({ judge, stale }: { judge: JudgeOut; stale: boolean }) {
  return (
    <>
      {stale && (
        <span className="choice-note">
          Your choice, {judge.model_id}, cannot be asked now - its provider is gone, closed to agents or down - so the
          Fast tier’s first is asked.
        </span>
      )}
      {judge.now === null && (
        <span className="choice-note">
          No model can be asked: Full auto’s judge stands aside and says so in the chat. Give a model a tier on the
          Models page.
        </span>
      )}
      {judge.now?.cli && <span className="choice-note">On a CLI each such command waits for it to start.</span>}
    </>
  )
}

/** Settings › The app › Agents (0.1.9): whom KOLONİ's judges ask, in every project - the Fast tier's first unless one
 *  is chosen; kept as it is changed. A choice that cannot be asked now stays chosen, and is said so. */
export function JudgeModel() {
  const [judge, setJudge] = useState<JudgeOut | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<JudgeOut>('/judge').then(setJudge, err => setError(errorText(err)))
  }, [])
  async function change(value: string) {
    const [provider_id, model_id] = value ? value.split('\n') : [null, null]
    setError(null)
    try {
      setJudge(await api.put<JudgeOut>('/judge', { provider_id, model_id }))
    } catch (err) {
      setError(errorText(err))
    }
  }
  // (Nothing to choose where a reply has no list - a stand-in server's in another page's tests.)
  const choices = judge?.choices ?? []
  const fast = choices.find(one => one.tier === 'fast')
  const chosen = judge?.provider_id && judge.model_id ? keyOf(judge.provider_id, judge.model_id) : ''
  const listed = choices.some(one => keyOf(one.provider_id, one.model_id) === chosen)
  return (
    <div className="settings-app-form">
      <Row
        label="Judge model"
        htmlFor="judge-model"
        doc={GUIDE.fullAutoJudge}
        why={JUDGE_WHY}
        warn={judge && <JudgeNotes judge={judge} stale={chosen !== '' && !listed} />}
      >
        <select
          id="judge-model"
          className="input"
          value={chosen}
          disabled={judge === undefined}
          onChange={e => void change(e.target.value)}
        >
          <option value="">Fast tier’s first (now: {fast ? fast.model_id : 'none'})</option>
          {choices.map(one => (
            <option key={keyOf(one.provider_id, one.model_id)} value={keyOf(one.provider_id, one.model_id)}>
              {one.provider_name} · {one.model_id} ({one.tier})
            </option>
          ))}
          {chosen && !listed && <option value={chosen}>{judge?.model_id} (cannot be asked now)</option>}
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
