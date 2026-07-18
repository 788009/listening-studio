import { afterEach, describe, expect, it } from 'vitest'

import {
  formatDate,
  matchLocale,
  setLocale,
  translate,
  translateApiError,
} from './index'

describe('i18n', () => {
  afterEach(() => setLocale('en'))

  it('matches supported locale variants and falls back to English', () => {
    expect(matchLocale('zh_cn')).toBe('zh-CN')
    expect(matchLocale('en-US')).toBe('en')
    expect(matchLocale('fr')).toBeNull()
    expect(setLocale('fr')).toBe('en')
  })

  it('translates fixed text, parameters, dates, and HTML lang', () => {
    setLocale('zh-CN')

    expect(translate('Library')).toBe('听力库')
    expect(translate('{count} exercises', { count: 3 })).toBe('3 个练习')
    expect(formatDate('2026-01-10T00:00:00Z')).toContain('2026')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('distinguishes user ID conflict reasons', () => {
    setLocale('zh-CN')

    expect(translateApiError('user_id_taken', 'fallback')).toBe(
      '该用户 ID 已被占用，请选择其他 ID',
    )
    expect(translateApiError('user_id_immutable', 'fallback')).toBe(
      '用户 ID 已经设置，不能再次修改',
    )
  })
})
