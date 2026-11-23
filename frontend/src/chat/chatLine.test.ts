import { beforeEach, expect, test } from 'vitest'
import type { ConvState } from '../state/applyEvent'
import { agent, assistantMessage, command, convState, fileChange, question, run, userMessage } from '../test-fixtures'
import { isLeadAsk, latestOf, leadQuestion, leadQuestions, storedWidth, waitingCards } from './chatLine'

test('the closed chat’s line is the Lead’s answer, not KOLONİ’s line said after it', () => {
  // R178: "Tester was not opened this turn." took the summary's place.
  const note = { ...assistantMessage('k', 'r', 'Tester was not opened this turn.'), role: 'koloni' as const, agent_id: null }
  const said = [userMessage('r', 'do it'), assistantMessage('m', 'r', 'All done.\nDetails'), note]
  expect(latestOf(convState({ runs: [run('r', 'completed')] }), said)).toBe('All done.')
  // (KOLONİ's line with no answer before it is still the newest.)
  expect(latestOf(convState({ runs: [run('r', 'failed')] }), [said[0], note])).toBe('Tester was not opened this turn.')
  // (B-205: nor KOLONİ's line under it on where the work is.)
  const landed = { ...assistantMessage('l', 'r', 'In the project: a.py (+1 −0).'), role: 'landed' as const, agent_id: null }
  expect(latestOf(convState({ runs: [run('r', 'completed')] }), [...said, landed])).toBe('All done.')
})

test('latestOf ignores checked', () => {
  const said = [userMessage('r', 'do it'), assistantMessage('m', 'r', 'All done.')]
  const checked = { ...assistantMessage('k', 'r', '✓ Tests passed: pytest -q'), role: 'checked' as const, agent_id: null }
  expect(latestOf(convState({ runs: [run('r', 'completed')] }), [...said, checked])).toBe('All done.')
})

test('the closed chat’s line says what the Orchestrator asks while it asks, before who else is at work', () => {
  const asked = 'Should mean() of an empty list raise ZeroDivisionError, or return 0?'
  const conv = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'running', { id: 'k', parent_agent_id: 'r', role_name: 'Coder', depth: 1 })],
    questions: [question('q', 'r', { question: `${asked}\nstats.py calls it.` })],
  })
  const said = [userMessage('r', 'fix mean'), assistantMessage('m', 'r', 'One thing first.')]
  expect(latestOf(conv, said)).toBe(`Orchestrator asks: ${asked}`)
  // KOLONİ's own card about one of its calls is not its question; answered, it asks nothing.
  for (const over of [{ leave: true }, { status: 'answered' as const }]) {
    expect(latestOf({ ...conv, questions: [{ ...conv.questions[0], ...over }] }, said)).toBe('Coder is working')
  }
})

beforeEach(() => localStorage.clear())

const at = run('r', 'waiting_approval')
// (A file a kept copy holds - B-156: one that holds none is no copy to take in.)
const held = { path: 'a.py', kind: 'changed', state: 'refused', whole: true, diff: null, additions: null, deletions: null, note: null } as ConvState['merges'][number]['files'][number]
// (Only what the count reads of each record: its status.)
const records = <T>(...statuses: string[]) => statuses.map((status, i) => ({ id: `x${i}`, run_id: 'r', agent_id: 'r', status }) as T)

test('every card that waits for the user is counted, of every kind, and nothing that does not wait', () => {
  const none = convState({ runs: [at], agents: [agent('r', 'waiting')] })
  expect(waitingCards(none)).toBe(0)
  const each: [Partial<ConvState>, number][] = [
    [{ questions: [question('q', 'r'), question('a', 'r', { status: 'answered' })] }, 1],
    [{ commands: [command('k', 'r', { status: 'proposed' }), command('d', 'r', { status: 'exited' })] }, 1],
    [{ pendingRoles: records<ConvState['pendingRoles'][number]>('', '') }, 2],
    [{ agents: [agent('r', 'waiting'), agent('r', 'proposed', { id: 'kid', depth: 1 }), agent('r', 'rejected', { id: 'no', depth: 1 })] }, 1],
    [{ webRequests: records<ConvState['webRequests'][number]>('proposed', 'approved') }, 1],
    [{ fileChanges: [fileChange('f', 'r', { status: 'proposed' }), fileChange('g', 'r', { status: 'applied' }), fileChange('h', 'r', { status: 'in_copy' })] }, 1],
    [{ merges: records<ConvState['merges'][number]>('pending', 'applied', 'interrupted') }, 1],
    // K-bekleyenler: one count with Ready for you's - a copy kept for Take in waits; a question asked again does not.
    [{ merges: [{ ...records<ConvState['merges'][number]>('interrupted')[0], kept_in: 'C:/copies/x', files: [held] }] }, 1],
    [{ questions: [question('s', 'r', { status: 'superseded', answer: 'Go on' }), question('c', 'r', { status: 'cancelled' })] }, 0],
    [
      {
        runs: [
          at,
          run('p', 'completed', { plan_turn: true, plan: { text: 'x', status: 'proposed', model_id: null, strongest: false } }),
          run('d', 'completed', { plan_turn: true, plan: { text: 'x', status: 'approved', model_id: null, strongest: false } }),
          // only the newest turn's plan can still be approved: an older one waits for nothing
          run('q', 'completed', { plan_turn: true, plan: { text: 'x', status: 'proposed', model_id: null, strongest: false } }),
        ],
      },
      1,
    ],
  ]
  for (const [over, count] of each) expect(waitingCards({ ...none, ...over }), Object.keys(over)[0]).toBe(count)
  // (Together, a later case's key takes an earlier one's place: the questions are those that wait for nothing.)
  expect(waitingCards(Object.assign({ ...none }, ...each.map(([over]) => over)))).toBe(8)
})

test('a width kept out of range starts at 420', () => {
  for (const kept of ['NaN', '200', '339', '761', '', '-1', 'wide']) {
    localStorage.setItem('koloni-chat-width', kept)
    expect(storedWidth(), kept).toBe(420)
  }
  localStorage.setItem('koloni-chat-width', '500')
  expect(storedWidth()).toBe(500)
  localStorage.removeItem('koloni-chat-width')
  expect(storedWidth()).toBe(420)
})

test('leadQuestions lists the Orchestrator’s open questions in order; leadQuestion is the first', () => {
  const conv = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r'), agent('r', 'running', { id: 'k', depth: 1, parent_agent_id: 'r' })],
    questions: [
      question('a', 'r', { question: 'First?' }),
      question('done', 'r', { status: 'answered', answer: 'yes' }),
      question('koloni', 'r', { leave: true, question: 'Allow?', options: ['Allow', 'Deny'] }),
      question('sub', 'r', { agent_id: 'k' }),
      question('b', 'r', { question: 'Second?' }),
    ],
  })
  expect(leadQuestions(conv).map(q => q.id)).toEqual(['a', 'b'])
  expect(leadQuestion(conv)?.id).toBe('a')
  // In its turn, its own question - asked or answered - is the Orchestrator's; KOLONİ's card and a sub-agent's are not.
  expect(conv.questions.filter(q => isLeadAsk(conv, q)).map(q => q.id)).toEqual(['a', 'done', 'b'])
})
