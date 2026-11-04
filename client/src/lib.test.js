import { describe, expect, it } from 'vitest'
import { buildQuery, changedFields, parseQuery, relativeTime, stageIndex } from './lib.js'

describe('url state', () => {
  it('round-trips filters', () => {
    const state = { ...parseQuery(''), view: 'board', stage: 'Work Report', owner: 'Ann Lee', flagged: true, page: 3, ticket: 105 }
    expect(parseQuery(buildQuery(state))).toMatchObject({ stage: 'Work Report', owner: 'Ann Lee', flagged: true, page: 3, ticket: 105 })
  })
  it('omits defaults', () => {
    expect(buildQuery(parseQuery(''))).toBe('')
  })
  it('ignores a garbage page number', () => {
    expect(parseQuery('?page=abc').page).toBe(1)
  })
})

describe('changedFields', () => {
  it('only reports differences and treats missing as empty', () => {
    expect(changedFields({ a: 'x', b: '' }, { a: 'x', b: 'y', c: '' })).toEqual({ b: 'y' })
  })
})

describe('stageIndex', () => {
  it('maps Done past the last step', () => {
    expect(stageIndex('Done')).toBe(6)
    expect(stageIndex('Assign Manager')).toBe(0)
    expect(stageIndex('Invoice')).toBe(5)
  })
})

describe('relativeTime', () => {
  it('is empty for junk and "now" for tiny gaps', () => {
    expect(relativeTime('nope')).toBe('')
    expect(relativeTime(new Date().toISOString())).not.toBe('')
  })
})
