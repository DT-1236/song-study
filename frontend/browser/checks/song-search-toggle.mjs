import { check } from '../harness.mjs'

// The new document form's "Search videos instead" toggle: flipping it repeats
// the last search for the other kind, flipping back reuses what was found,
// and a search still in flight for the old kind never lands. The search
// itself is stubbed, as it reaches YouTube Music.
await check('song-search-toggle', async (h) => {
  const page = await h.open('/new')
  const requests = []
  // Songs answer slowly, so a flip can overtake them.
  await page.route('**/songs/search?*', async (route) => {
    const url = new URL(route.request().url())
    const kind = url.searchParams.get('videos') ? 'videos' : 'songs'
    const q = url.searchParams.get('q')
    requests.push(`${kind}:${q}`)
    await new Promise((done) => setTimeout(done, kind === 'songs' ? 1500 : 0))
    await route.fulfill({
      json: [
        {
          video_id: `${kind}-${q}`,
          title: `${kind}:${q}`,
          artists: null,
          album: null,
          duration_seconds: null,
          thumbnail_url: null,
        },
      ],
    })
  })
  const box = page.locator('#song-search-query')
  const toggle = page.locator('.search-include-videos input')
  const shown = () => page.locator('.search-result-title').allTextContents()
  async function expectShown(title, message) {
    await page
      .locator('.search-result-title', { hasText: title })
      .waitFor()
      .catch(() => {})
    // Long enough for a stale songs answer to land, if it were going to.
    await page.waitForTimeout(2000)
    const titles = await shown()
    h.expect(
      titles.length === 1 && titles[0] === title,
      message,
      JSON.stringify(titles),
    )
  }

  h.step('flipping before any search searches nothing')
  await page.waitForSelector('.new-document-form')
  await toggle.check()
  await toggle.uncheck()
  await page.waitForTimeout(300)
  h.expect(requests.length === 0, 'no search', JSON.stringify(requests))

  h.step('a flip repeats the search for the other kind')
  await box.fill('one')
  await box.press('Enter')
  await expectShown('songs:one', 'songs found')
  await toggle.check()
  await expectShown('videos:one', 'videos found after the flip')

  h.step('flipping back reuses the songs found')
  await toggle.uncheck()
  await expectShown('songs:one', 'songs shown again')
  h.expect(
    requests.join() === 'songs:one,videos:one',
    'no search on flipping back',
    JSON.stringify(requests),
  )

  h.step('a flip mid-search drops the old kind')
  await box.fill('two')
  await box.press('Enter')
  await page.waitForTimeout(200)
  await toggle.check()
  await expectShown('videos:two', 'videos win over songs still in flight')

  h.step('flipping back uses the songs that settled for the same query')
  const before = requests.length
  await toggle.uncheck()
  await expectShown('songs:two', 'songs shown')
  h.expect(
    requests.length === before,
    'no search for songs already found',
    JSON.stringify(requests),
  )

  h.step('a new query clears what was found')
  await box.fill('three')
  await box.press('Enter')
  await expectShown('songs:three', 'songs for the new query')
  await toggle.check()
  await expectShown('videos:three', 'videos for the new query')
})
