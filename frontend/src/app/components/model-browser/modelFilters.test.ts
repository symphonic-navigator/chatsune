import { describe, expect, it } from 'vitest'
import type { EnrichedModelDto } from '../../../core/types/llm'
import { applyModelFilters, type BillingFilter } from './modelFilters'

function makeModel(
  billing: 'free' | 'subscription' | 'pay_per_token' | null | undefined,
  overrides: Partial<EnrichedModelDto> = {},
): EnrichedModelDto {
  return {
    connection_id: 'c1',
    connection_slug: 's',
    connection_display_name: 'D',
    model_id: 'm1',
    display_name: 'Model',
    context_window: 128000,
    supports_reasoning: false,
    supports_vision: false,
    supports_tool_calls: false,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    unique_id: 's:m1',
    billing_category: billing === undefined ? undefined : billing,
    user_config: null,
    ...overrides,
  } as EnrichedModelDto
}

describe('applyModelFilters — billing', () => {
  const free = makeModel('free', { model_id: 'free-m', unique_id: 's:free-m' })
  const sub = makeModel('subscription', { model_id: 'sub-m', unique_id: 's:sub-m' })
  const pay = makeModel('pay_per_token', { model_id: 'pay-m', unique_id: 's:pay-m' })
  const unknown = makeModel(null, { model_id: 'unk-m', unique_id: 's:unk-m' })
  const all = [free, sub, pay, unknown]

  it('all (or undefined) lets everything through', () => {
    expect(applyModelFilters(all, {})).toEqual(all)
    expect(applyModelFilters(all, { billing: 'all' })).toEqual(all)
  })

  it('no_per_token keeps free + subscription, drops pay_per_token and unknown', () => {
    const result = applyModelFilters(all, { billing: 'no_per_token' })
    expect(result.map((m) => m.model_id).sort()).toEqual(['free-m', 'sub-m'])
  })

  it('free keeps only free, drops subscription/pay/unknown', () => {
    const result = applyModelFilters(all, { billing: 'free' })
    expect(result.map((m) => m.model_id)).toEqual(['free-m'])
  })

  it('subscription keeps only subscription, drops the rest', () => {
    const result = applyModelFilters(all, { billing: 'subscription' })
    expect(result.map((m) => m.model_id)).toEqual(['sub-m'])
  })

  it('pay_per_token keeps only pay_per_token, drops the rest', () => {
    const result = applyModelFilters(all, { billing: 'pay_per_token' })
    expect(result.map((m) => m.model_id)).toEqual(['pay-m'])
  })

  it('null billing_category is excluded by every filter except all', () => {
    const filters: BillingFilter[] = [
      'no_per_token',
      'free',
      'subscription',
      'pay_per_token',
    ]
    for (const billing of filters) {
      const result = applyModelFilters([unknown], { billing })
      expect(result, `filter=${billing}`).toEqual([])
    }
  })

  it('billing filter composes with capability filters', () => {
    const visionFree = makeModel('free', {
      model_id: 'vf', unique_id: 's:vf', supports_vision: true,
    })
    const visionPay = makeModel('pay_per_token', {
      model_id: 'vp', unique_id: 's:vp', supports_vision: true,
    })
    const textFree = makeModel('free', { model_id: 'tf', unique_id: 's:tf' })
    const result = applyModelFilters(
      [visionFree, visionPay, textFree],
      { billing: 'free', capVision: true },
    )
    expect(result.map((m) => m.model_id)).toEqual(['vf'])
  })
})
