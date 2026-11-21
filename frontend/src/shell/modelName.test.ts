import { expect, test } from 'vitest'
import { autoPicked, modelName, pickedWhy, ranOn } from './modelName'

test('a model id that is a file path is shown by its file name', () => {
  expect(modelName('C:/Users/me/models/Qwen3.8-27B-UD-Q3_K_XL_D3.gguf')).toBe('Qwen3.8-27B-UD-Q3_K_XL_D3')
  expect(modelName('C:\\models\\tiny.GGUF')).toBe('tiny')
  expect(modelName('/srv/models/phi.gguf')).toBe('phi')
})

test('plain ids are kept and a missing id says so', () => {
  expect(modelName('gpt-oss:20b')).toBe('gpt-oss:20b')
  expect(modelName('org/model-name')).toBe('org/model-name')
  expect(modelName(null)).toBe('model unknown')
})

test('a CLI that ran on its own default and did not say which is not given a name', () => {
  expect(modelName('codex default')).toBe('CLI default (model not reported)')
  expect(modelName('claude-haiku-4-5-20251001')).toBe('claude-haiku-4-5-20251001')
})

test('where an agent runs is its provider and model, and says when the name is from settings', () => {
  expect(ranOn('Fast', 'deep')).toBe('Fast · deep')
  expect(ranOn('Codex', 'gpt-5.5-codex', 'settings')).toBe("Codex · gpt-5.5-codex (from Codex's settings)")
  expect(ranOn('Codex', 'codex default')).toBe('Codex · CLI default (model not reported)')
  // asked for auto, Copilot's auto picked it; asked for fusion, its fusion
  expect(ranOn('Copilot', 'gpt-6-luna', 'auto')).toBe('Copilot · auto → gpt-6-luna')
  expect(ranOn('Copilot', 'gpt-6-luna', 'fusion')).toBe('Copilot · fusion → gpt-6-luna')
  // nothing is made up: a model nobody knows is left out, and so is a provider
  expect(ranOn('Fast', null)).toBe('Fast')
  expect(ranOn(null, 'qwen')).toBe('qwen')
  expect(ranOn(null, null)).toBe('')
})

test('why Copilot’s auto or fusion picked a model is read from its note, as KOLONİ wrote it there; nothing else is', () => {
  const why = 'Copilot Fusion selected GPT-6 Luna since the task has low complexity.'
  expect(autoPicked('fusion')).toBe('fusion → ')
  expect(autoPicked('settings')).toBe('')
  // (After the rest of its note: its level's.)
  expect(pickedWhy(`high → none: auto takes no level. Copilot's fusion picked gpt-6-luna: “${why}”`)).toBe(why)
  expect(pickedWhy(`Copilot's auto picked gpt-6-luna: “Easy "one".”`)).toBe('Easy "one".')
  expect(pickedWhy('high → none: auto takes no level.')).toBeNull()
  expect(pickedWhy(null)).toBeNull()
})
