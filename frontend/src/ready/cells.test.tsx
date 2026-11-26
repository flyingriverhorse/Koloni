import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { AwayJob, BacklogTask } from '../api/types'
import { Cell } from '../shell/Cell'
import { CELL, jobStands, taskStands } from './cells'

const task = (over: Partial<BacklogTask>) => ({ status: 'todo', not_in: false, waiting: false, ...over }) as BacklogTask

test('a cell is named by its label, its title too: its colour never says it alone', () => {
  render(<Cell {...CELL.stuck} label="stuck: 2 tests fail" big />)
  const cell = screen.getByRole('img', { name: 'stuck: 2 tests fail' })
  expect(cell).toHaveAttribute('title', 'stuck: 2 tests fail')
  expect(cell).toHaveClass('cell', 'cell-warn', 'cell-full', 'cell-big')
})

test('a task stands as its row says it; a night job as its lane does', () => {
  expect(taskStands(task({ status: 'done' }))).toEqual(['done', 'done'])
  expect(taskStands(task({ status: 'done' }), true)).toEqual(['done', 'done'])
  expect(taskStands(task({}), true)).toEqual(['yours', 'push waits for you'])
  expect(taskStands(task({ status: 'review' }))).toEqual(['yours', 'done?'])
  expect(taskStands(task({ status: 'review', not_in: true }))).toEqual(['yours', 'waits for Take in'])
  expect(taskStands(task({ status: 'doing' }))).toEqual(['running', 'at work'])
  expect(taskStands(task({ status: 'doing', waiting: true }))).toEqual(['yours', 'waits for you'])
  expect(taskStands(task({ status: 'blocked', stuck: 'tests fail' }))).toEqual(['stuck', 'stuck'])
  expect(taskStands(task({ place: 2 }))).toEqual(['queued', 'queued'])
  expect(taskStands(task({}))).toEqual(['queued', 'to do'])
  const job = (state: AwayJob['state']) => jobStands({ state } as AwayJob)
  expect(['done', 'working', 'waits', 'failed', 'stopped', 'next'].map(one => job(one as AwayJob['state']))).toEqual([
    'done',
    'running',
    'yours',
    'stuck',
    'queued',
    'queued',
  ])
})
