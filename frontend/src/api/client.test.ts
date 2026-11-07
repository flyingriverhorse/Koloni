import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, api } from './client'

afterEach(() => vi.unstubAllGlobals())

const answer = (status: number, body: unknown) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, statusText: 'Unprocessable Entity' })))

test('a refusal in the server’s words is thrown as it was said', async () => {
  answer(422, { detail: 'a trigger needs a name of at most 80 characters' })
  await expect(api.post('/x')).rejects.toMatchObject({ status: 422, detail: 'a trigger needs a name of at most 80 characters' })
})

test('a refusal that names fields says which field and what is wrong with it', async () => {
  answer(422, {
    detail: [
      { type: 'less_than_equal', loc: ['body', 'budget', 'steps'], msg: 'Input should be less than or equal to 200' },
      { type: 'missing', loc: ['body', 'name'], msg: 'Field required' },
    ],
  })
  const thrown = await api.post('/x').catch((err: unknown) => err)
  expect(thrown).toBeInstanceOf(ApiError)
  expect((thrown as ApiError).detail).toBe('budget.steps: Input should be less than or equal to 200; name: Field required')
})

test('a refusal that says nothing readable is the status it came with', async () => {
  answer(422, { detail: [{ nothing: true }] })
  await expect(api.post('/x')).rejects.toMatchObject({ detail: '422 Unprocessable Entity' })
  answer(422, {})
  await expect(api.post('/x')).rejects.toMatchObject({ detail: '422 Unprocessable Entity' })
})
