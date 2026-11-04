import { describe, expect, it } from 'vitest'
import { buildQuery, changedFields, explainProblem, nextAction, parseQuery, relativeTime, stageIndex, stepLabel } from './lib.js'

describe('url state', () => {
  it('round-trips filters', () => {
    const state = { ...parseQuery(''), view: 'jobs', stage: 'Work Report', owner: 'Ann Lee', flagged: true, page: 3, ticket: 105 }
    expect(parseQuery(buildQuery(state))).toMatchObject({ view: 'jobs', stage: 'Work Report', owner: 'Ann Lee', flagged: true, page: 3, ticket: 105 })
  })
  it('omits defaults, and home is the default page', () => {
    expect(buildQuery(parseQuery(''))).toBe('')
    expect(parseQuery('').view).toBe('home')
  })
  it('ignores a garbage page number', () => {
    expect(parseQuery('?page=abc').page).toBe(1)
  })
})

describe('plain-language wording', () => {
  it('says who needs to do what, for every step', () => {
    expect(nextAction({ stage: 'Purchase Order', actionOwner: 'Nefo Zagi' })).toBe("Nefo Zagi needs to get the customer's Purchase Order.")
    expect(nextAction({ stage: 'Work Report', actionOwner: 'Ana Gil' })).toBe('Ana Gil needs to upload the Work Report.')
    expect(nextAction({ stage: 'Assign Manager', actionOwner: 'Farho Kelpar' })).toContain('assign a manager')
  })
  it('handles finished jobs and a missing owner', () => {
    expect(nextAction({ stage: 'Done', actionOwner: '' })).toMatch(/Nothing left to do/)
    expect(nextAction({ stage: 'Invoice', actionOwner: '' })).toMatch(/^Someone on the team needs to add the Invoice/)
  })
  it('explains each kind of problem and never hides an unknown one', () => {
    expect(explainProblem('Closed but waiting on Invoice').title).toMatch(/Marked Closed.*Invoice/)
    expect(explainProblem('Resolved without Work Report').help).toMatch(/Work Report/)
    expect(explainProblem('Delivery Note is not a link').title).toMatch(/Delivery Note has text that is not a link/)
    expect(explainProblem('Purchase Order cannot be NA').title).toMatch(/always required/)
    expect(explainProblem('Something new').title).toBe('Something new')
  })
  it('labels progress', () => {
    expect(stepLabel('Assign Manager')).toBe('Step 1 of 6')
    expect(stepLabel('Invoice')).toBe('Step 6 of 6')
    expect(stepLabel('Done')).toBe('Finished')
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
  it('is empty for junk and "just now" for tiny gaps', () => {
    expect(relativeTime('nope')).toBe('')
    expect(relativeTime(new Date().toISOString())).toBe('just now')
  })
})
