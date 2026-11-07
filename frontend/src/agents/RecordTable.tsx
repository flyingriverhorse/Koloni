import type { RecordRow } from '../api/types'
import { recordSummary, rediscoveryLine, round, time, where } from './record'
import { money } from '../usage/cost'
import { Section } from './RoleEditor'

const UNKNOWN = 'not every agent reported it'

/** A middle value of the record; the record has none unless every agent reported it - never a zero. */
function Middle({ value, say }: { value: number | null; say: (n: number) => string }) {
  return value === null ? (
    <td className="mono" title={UNKNOWN}>
      <span aria-hidden="true">–</span>
      <span className="visually-hidden">{UNKNOWN}</span>
    </td>
  ) : (
    <td className="mono">{say(value)}</td>
  )
}

/** A role's record of the last 30 days, model by model: measured, not judged. */
export function RecordTable({ record }: { record: RecordRow[] }) {
  const reads = rediscoveryLine(record)
  return (
  <Section title="Last 30 days">
    {/* K-devir-0: how much its sub-agents read before writing; nothing where none has it on record. */}
    {reads && <p className="muted provider-note">{reads}</p>}
    {record.length > 0 && (
      // Folded, closed (it takes much room): its line says the gist. Open or closed is not remembered.
      <details className="more role-record">
        <summary>Record of the last 30 days: {recordSummary(record)}</summary>
        {/* A narrow window scrolls the table, not the page. */}
        <div className="tools-table">
          <table className="usage-table" aria-label="Record of the last 30 days">
            <thead>
              <tr>
                <th scope="col">Provider · model</th>
                <th scope="col">Ran</th>
                <th scope="col">Done</th>
                <th scope="col">Failed</th>
                <th scope="col">Stopped</th>
                <th scope="col">Interrupted</th>
                <th scope="col">Steps</th>
                <th scope="col">Time</th>
                <th scope="col">Sent</th>
                <th scope="col">Written</th>
                <th scope="col">Changes taken / rejected</th>
                <th scope="col">Chosen in comparisons</th>
                <th scope="col">Taken in</th>
                <th scope="col">Turned down</th>
                <th scope="col">Cost</th>
              </tr>
            </thead>
            <tbody>
              {record.map(row => (
                <tr key={`${row.provider_name} ${row.model_id}`}>
                  <th scope="row" className="mono">
                    {where(row)}
                  </th>
                  <td className="mono">{row.agents}</td>
                  <td className="mono">{row.ended.done}</td>
                  <td className="mono">{row.ended.failed}</td>
                  <td className="mono" title={`${row.ended.stopped_by_koloni} by KOLONİ, ${row.ended.stopped_by_user} by you`}>
                    {row.ended.stopped_by_koloni + row.ended.stopped_by_user}
                    <span className="visually-hidden">
                      : {row.ended.stopped_by_koloni} by KOLONİ, {row.ended.stopped_by_user} by you
                    </span>
                  </td>
                  <td className="mono">{row.ended.interrupted}</td>
                  <Middle value={row.steps} say={round} />
                  <Middle value={row.seconds} say={time} />
                  <Middle value={row.input_tokens} say={round} />
                  <Middle value={row.output_tokens} say={round} />
                  <td className="mono">
                    {row.changes.taken} / {row.changes.rejected}
                  </td>
                  <td className="mono">
                    {row.compared.chosen + row.compared.not_chosen ? `${row.compared.chosen} of ${row.compared.chosen + row.compared.not_chosen}` : '–'}
                  </td>
                  {/* K-model-puan: jobs done with nothing turned down; turned down as a whole; the middle cost as Usage prices it. */}
                  <td className="mono">{row.taken_in}</td>
                  <td className="mono">{row.turned_down}</td>
                  <td className="mono" title={row.cost ? undefined : 'not priced, or not every agent’s cost is whole'}>
                    {money(row.cost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted provider-note">Middle values: half the agents took more, half less.</p>
      </details>
    )}
    {record.length === 0 && (
      <p className="muted provider-note">No agent of this role ended in the last 30 days.</p>
    )}
  </Section>
  )
}
