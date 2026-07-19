import { Buffer } from 'node:buffer'

import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

const longToken = `climate_${'adaptation'.repeat(18)}`
const createdAt = '2026-07-01T08:00:00Z'
const appOrigin = 'http://127.0.0.1:4174'

const topicTag = {
  id: 11,
  type: 'topic',
  englishValue: longToken,
  displayValue: longToken,
  fullTag: `topic:${longToken}`,
  translations: [],
}
const categoryTag = {
  id: 12,
  type: 'category',
  englishValue: 'classroom_interview',
  displayValue: 'classroom_interview',
  fullTag: 'category:classroom_interview',
  translations: [],
}
const authorTag = {
  id: 13,
  type: 'author',
  englishValue: 'TeacherOne',
  displayValue: 'TeacherOne',
  fullTag: 'author:TeacherOne',
  translations: [],
}
const publicAudio = {
  id: 1,
  author: { userId: 'TeacherOne', username: 'Teacher One' },
  title: `A practical listening exercise about ${longToken}`,
  text: 'Host: How can schools prepare?\nLearner: They can plan and work together.',
  sourceType: 'multi_turn',
  status: 'ready',
  visibility: 'public',
  durationSeconds: 42,
  sampleRate: 8000,
  tags: [authorTag, topicTag, categoryTag],
  utterances: [
    {
      voiceId: 1,
      speakerDisplayName: 'Host',
      text: 'How can schools prepare?',
      position: 0,
    },
    {
      voiceId: 2,
      speakerDisplayName: 'Learner',
      text: 'They can plan and work together.',
      position: 1,
    },
  ],
}
const voices = [
  {
    id: 1,
    author: { userId: 'TeacherOne', username: 'Teacher One' },
    title: `Host voice ${longToken}`,
    status: 'ready',
    visibility: 'private',
    sampleSource: 'original',
    tags: [],
  },
  {
    id: 2,
    author: { userId: 'TeacherOne', username: 'Teacher One' },
    title: 'Learner voice',
    status: 'ready',
    visibility: 'public',
    sampleSource: 'original',
    tags: [],
  },
]

interface PageMonitor {
  assertClean(): void
}

function monitorPage(page: Page): PageMonitor {
  const errors: string[] = []
  page.on('console', (message) => {
    const expectedAnonymousProbe =
      message.text().includes('401') &&
      message.location().url.length > 0 &&
      new URL(message.location().url).pathname === '/api/users/me'
    if (expectedAnonymousProbe) return
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', (error) => errors.push(`page: ${error.message}`))
  page.on('requestfailed', (request) => {
    errors.push(`request: ${request.method()} ${request.url()} ${request.failure()?.errorText}`)
  })
  page.on('response', (response) => {
    const expectedAnonymousProbe =
      response.status() === 401 && new URL(response.url()).pathname === '/api/users/me'
    if (response.status() >= 400 && !expectedAnonymousProbe) {
      errors.push(`response: ${response.status()} ${response.url()}`)
    }
  })
  return {
    assertClean() {
      expect(errors, errors.join('\n')).toEqual([])
    },
  }
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
    headers: { 'X-Request-ID': 'playwright-request' },
  })
}

async function mockBackend(page: Page, teacher: boolean): Promise<void> {
  await page.route(`${appOrigin}/media/**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'audio/wav',
      body: Buffer.from('RIFFmock-wave-data'),
    })
  })
  await page.route(`${appOrigin}/api/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const { pathname } = url
    const method = request.method()

    if (pathname === '/api/users/me') {
      if (!teacher) {
        await json(
          route,
          {
            error: {
              code: 'authentication_required',
              message: 'Authentication required',
              details: null,
              request_id: 'playwright-request',
            },
          },
          401,
        )
        return
      }
      await json(route, {
        userId: 'TeacherOne',
        username: 'Teacher One',
        locale: 'en',
        profileComplete: true,
      })
      return
    }
    if (pathname === '/api/audio-tags/autocomplete') {
      await json(route, [`topic:${longToken}`, 'category:classroom_interview'])
      return
    }
    if (pathname === '/api/audio-tags') {
      const type = url.searchParams.get('type')
      const tags =
        type === 'topic'
          ? [topicTag]
          : type === 'category'
            ? [categoryTag]
            : [topicTag, categoryTag]
      await json(route, tags)
      return
    }
    if (pathname === '/api/voice-tags') {
      await json(route, [
        {
          id: 21,
          type: 'gender',
          englishValue: 'female',
          displayValue: 'Female',
          fullTag: 'gender:female',
          translations: [],
        },
      ])
      return
    }
    if (pathname === '/api/voices' && method === 'GET') {
      await json(route, { items: voices, page: 1, pageSize: 100, total: voices.length })
      return
    }
    if (pathname === '/api/audios' && method === 'GET') {
      await json(route, { items: [publicAudio], page: 1, pageSize: 20, total: 1 })
      return
    }
    if (pathname === '/api/audios/dialogues' && method === 'POST') {
      await json(route, { audioId: 7, jobId: 51 }, 202)
      return
    }
    if (pathname === '/api/audios/1' && method === 'GET') {
      await json(route, publicAudio)
      return
    }
    if (pathname === '/api/jobs/51') {
      await json(route, {
        id: 51,
        type: 'audio_synthesis',
        status: 'running',
        progress: 42,
        inputSummary: {},
        cancelRequested: false,
        retryable: true,
        attemptCount: 1,
        createdAt,
        updatedAt: createdAt,
      })
      return
    }
    if (pathname === '/api/generation-batches/9') {
      await json(route, {
        id: 9,
        jobId: 52,
        questionTypes: ['multiple_choice'],
        requestedCount: 1,
        status: 'completed',
        progress: 100,
        tags: [{ id: topicTag.id, type: 'topic', englishValue: longToken }],
        items: [
          {
            id: 90,
            position: 0,
            status: 'completed',
            audioId: 1,
            attemptCount: 1,
            title: publicAudio.title,
          },
        ],
        speakerVoices: [
          { speaker: 'Host', voiceId: 1 },
          { speaker: 'Learner', voiceId: 2 },
        ],
        createdAt,
        updatedAt: createdAt,
      })
      return
    }
    if (pathname === '/api/paper-presets') {
      await json(route, [
        {
          id: 1,
          name: 'Standard',
          isBuiltin: true,
          introSilenceMilliseconds: 1000,
          interItemSilenceMilliseconds: 2000,
          repeatCount: 2,
          outroSilenceMilliseconds: 1000,
        },
      ])
      return
    }
    if (pathname === '/api/resource-management') {
      const kind = url.searchParams.get('kind') ?? 'voice'
      await json(route, {
        items: [
          {
            id: 1,
            kind,
            title: `${kind} ${longToken}`,
            status: kind === 'generation_batch' ? 'completed' : 'ready',
            visibility: kind === 'voice' || kind === 'audio' ? 'private' : undefined,
            tags: [{ id: 11, type: 'topic', value: longToken }],
            createdAt,
            references: [{ type: 'audio_utterance', count: 2 }],
            canDelete: false,
          },
        ],
        page: 1,
        pageSize: 20,
        total: 1,
      })
      return
    }

    await json(route, { error: `Unexpected mock request: ${method} ${pathname}` }, 500)
  })
}

async function expectNoViewportOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }))
  expect(dimensions.document, JSON.stringify(dimensions)).toBeLessThanOrEqual(
    dimensions.viewport + 1,
  )
  expect(dimensions.body, JSON.stringify(dimensions)).toBeLessThanOrEqual(
    dimensions.viewport + 1,
  )
}

async function expectNoOverlap(locator: Locator): Promise<void> {
  const boxes = await locator.evaluateAll((elements) =>
    elements
      .filter((element) => {
        const style = getComputedStyle(element)
        return style.display !== 'none' && style.visibility !== 'hidden'
      })
      .map((element) => {
        const box = element.getBoundingClientRect()
        return { x: box.x, y: box.y, width: box.width, height: box.height }
      }),
  )
  for (let left = 0; left < boxes.length; left += 1) {
    for (let right = left + 1; right < boxes.length; right += 1) {
      const a = boxes[left]
      const b = boxes[right]
      if (!a || !b) continue
      const overlapWidth = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
      const overlapHeight = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
      expect(
        overlapWidth > 1 && overlapHeight > 1,
        `elements ${left} and ${right} overlap`,
      ).toBe(false)
    }
  }
}

async function expectTextContrast(locator: Locator): Promise<void> {
  const ratio = await locator.evaluate((element) => {
    function rgb(value: string): number[] {
      return value.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? [0, 0, 0]
    }
    function luminance(values: number[]): number {
      const channels = values.map((value) => {
        const normalized = value / 255
        return normalized <= 0.03928
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4
      })
      return (
        0.2126 * (channels[0] ?? 0) +
        0.7152 * (channels[1] ?? 0) +
        0.0722 * (channels[2] ?? 0)
      )
    }
    const foreground = luminance(rgb(getComputedStyle(element).color))
    let backgroundElement: Element | null = element
    let background = [255, 255, 255]
    while (backgroundElement) {
      const value = getComputedStyle(backgroundElement).backgroundColor
      if (value !== 'rgba(0, 0, 0, 0)') {
        background = rgb(value)
        break
      }
      backgroundElement = backgroundElement.parentElement
    }
    const backgroundLuminance = luminance(background)
    return (
      (Math.max(foreground, backgroundLuminance) + 0.05) /
      (Math.min(foreground, backgroundLuminance) + 0.05)
    )
  })
  expect(ratio).toBeGreaterThanOrEqual(4.5)
}

test('anonymous student can search and inspect public audio', async ({ page }, testInfo) => {
  const monitor = monitorPage(page)
  await mockBackend(page, false)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Listening Studio' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Create', exact: true })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Batch' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Manage' })).toHaveCount(0)

  await page.keyboard.press('Tab')
  const skipLink = page.getByRole('link', { name: 'Skip to content' })
  await expect(skipLink).toBeFocused()
  await expect(skipLink).toBeVisible()

  await page.screenshot({
    path: testInfo.outputPath('student-home-light.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Use dark theme' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expectTextContrast(page.getByRole('heading', { name: 'Listening Studio' }))
  await page.screenshot({
    path: testInfo.outputPath('student-home-dark.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: 'Use light theme' }).click()

  await page.getByRole('link', { name: 'Library', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Listening library' })).toBeVisible()
  await expectTextContrast(page.getByText('Public audio'))

  const search = page.getByRole('combobox', { name: 'Search audio' })
  await search.fill('topic:climate')
  await expect(page.getByRole('option').first()).toBeVisible()
  await search.press('ArrowDown')
  await search.press('Enter')
  await expect(search).toHaveValue(`topic:${longToken} `)
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page.getByRole('link', { name: publicAudio.title })).toBeVisible()
  await expect(page.locator('audio')).toBeVisible()
  await expectNoViewportOverflow(page)
  await expectNoOverlap(page.locator('header nav a'))
  await page.screenshot({
    path: testInfo.outputPath('student-library.png'),
    fullPage: true,
    animations: 'disabled',
  })

  await page.getByRole('link', { name: publicAudio.title }).click()
  await expect(page.getByRole('heading', { name: publicAudio.title })).toBeVisible()
  await expect(page.getByText('Host', { exact: true })).toBeVisible()
  await expect(page.getByText('Learner', { exact: true })).toBeVisible()
  await expect(page.locator('audio')).toHaveAttribute('controls', '')
  await expectNoViewportOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('student-audio-detail.png'),
    fullPage: true,
    animations: 'disabled',
  })
  monitor.assertClean()
})

test('teacher forms, task states, tabs, and lists remain usable', async ({ page }, testInfo) => {
  const monitor = monitorPage(page)
  await mockBackend(page, true)
  await page.goto('/create')
  for (const name of ['Create', 'Batch', 'Papers', 'Voices', 'Manage']) {
    await expect(page.getByRole('link', { name, exact: true })).toBeVisible()
  }
  await expect(page.getByLabel('Title')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Creation mode' })).toBeVisible()
  await page.getByRole('button', { name: 'Dialogue', exact: true }).click()
  await expect(page.getByLabel('Speaker')).toBeVisible()
  await expect(page.getByLabel('Voice').first()).toContainText(longToken)
  await page.getByLabel('Title').fill('Browser dialogue')
  await page.getByLabel('Speaker').fill('Host')
  await page.getByLabel('Text', { exact: true }).fill('First browser-tested turn.')
  await page.getByRole('button', { name: 'Add turn' }).click()
  await page.getByLabel('Speaker').nth(1).fill('Learner')
  await page.getByLabel('Text', { exact: true }).nth(1).fill('Second browser-tested turn.')
  await expectNoOverlap(page.locator('ol select, ol input, ol textarea'))
  await page.getByRole('button', { name: 'Generate audio' }).click()
  const audioProgress = page.getByRole('progressbar', { name: 'Audio generation progress' })
  await expect(audioProgress).toHaveAttribute('aria-valuenow', '42')
  await expect(page.getByText('Generating audio')).toBeVisible()
  await expectNoViewportOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('teacher-dialogue-task.png'),
    fullPage: true,
    animations: 'disabled',
  })

  await page.goto('/generate/9')
  await expect(page.getByRole('progressbar', { name: 'Batch generation progress' })).toHaveAttribute(
    'aria-valuenow',
    '100',
  )
  await expect(page.getByText('Completed', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('link', { name: publicAudio.title })).toBeVisible()
  await expectNoViewportOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('teacher-batch-status.png'),
    fullPage: true,
    animations: 'disabled',
  })

  await page.goto('/papers/new')
  await expect(page.getByLabel('Paper title')).toBeVisible()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText('1 selected').first()).toBeVisible()
  await expectNoViewportOverflow(page)

  await page.goto('/manage')
  const selectedTab = page.getByRole('tab', { selected: true })
  await expect(selectedTab).toHaveText('My voices')
  await selectedTab.focus()
  await selectedTab.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'My audios' })).toBeFocused()
  await expect(page.getByRole('tab', { name: 'My audios' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByText(`audio ${longToken}`)).toBeVisible()
  await expect(page.getByText('Referenced by 2 audio utterance')).toBeVisible()
  await expectNoOverlap(page.getByRole('tab'))
  await expectNoViewportOverflow(page)
  await page.screenshot({
    path: testInfo.outputPath('teacher-management.png'),
    fullPage: true,
    animations: 'disabled',
  })
  monitor.assertClean()
})
