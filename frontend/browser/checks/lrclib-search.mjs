import { check } from '../harness.mjs'

// The new document form's LRCLIB search: it takes a title, an artist or both
// (but needs one), a failed search keeps the earlier results with a note that
// they're stale, and a rate limit disables the button for as long as the
// server said. The search itself is stubbed, as it reaches LRCLIB.
await check('lrclib-search', async (h) => {
  // The failed search below is stubbed on purpose.
  h.expectServerError('/lrclib/search')
  const page = await h.open('/new')
  let respond = () => ({ json: [] })
  const seen = await h.stub(page, '**/lrclib/search?*', () => respond())
  const found = (name) => ({
    json: [
      {
        id: 1,
        uri: 'https://lrclib.net/api/get/1',
        track_name: name,
        artist_name: 'Some Artist',
        album_name: '',
        duration: 200,
        synced: false,
        title_match: 'whole',
        duration_delta: 0,
        within_tolerance: true,
        preview: [],
      },
    ],
  })
  const title = page.locator('#lrclib-search-query')
  const artist = page.locator('#lrclib-search-artist')
  const lrclibButton = page
    .locator('.search-dropdown', { has: title })
    .locator('.search-dropdown-button')
  const shown = () => page.locator('.search-result-title').allTextContents()

  h.step('a search needs a title or an artist')
  await page.waitForSelector('.new-document-form')
  h.expect(await lrclibButton.isDisabled(), 'disabled with both empty')
  await artist.fill('Some Artist')
  h.expect(await lrclibButton.isEnabled(), 'enabled with only an artist')

  h.step('an artist alone is searched')
  respond = () => found('First Song')
  await artist.press('Enter')
  await page
    .locator('.search-result-title', { hasText: 'First Song' })
    .waitFor()
  const sent = seen.map((url) => Object.fromEntries(url.searchParams))
  h.expect(
    sent.length === 1 &&
      sent[0].title === '' &&
      sent[0].artist === 'Some Artist',
    'the artist was sent without a title',
    JSON.stringify(sent),
  )

  h.step('a title alone is searched')
  await artist.fill('')
  await title.fill('First Song')
  h.expect(await lrclibButton.isEnabled(), 'enabled with only a title')

  h.step('a failed search keeps the results and says they may be stale')
  respond = () => ({ status: 502, json: { detail: 'LRCLIB is down.' } })
  await title.press('Enter')
  await page.locator('.form-error', { hasText: 'LRCLIB is down.' }).waitFor()
  h.expect(
    (await shown()).join() === 'First Song',
    'the earlier results are still listed',
    JSON.stringify(await shown()),
  )
  h.expect(
    (await page.locator('.search-dropdown-stale').count()) === 1,
    'the stale note is shown',
  )

  h.step('a rate limit disables the button for the time given')
  respond = () => ({
    status: 429,
    json: { detail: 'Rate limited.', retry_after_seconds: 0.4 },
  })
  await lrclibButton.click()
  await page.locator('.form-error', { hasText: 'Rate limited.' }).waitFor()
  h.expect(await lrclibButton.isDisabled(), 'disabled while limited')
  const before = seen.length
  await title.press('Enter')
  h.expect(seen.length === before, 'Enter searches nothing meanwhile')
  await page.waitForTimeout(700)
  h.expect(await lrclibButton.isEnabled(), 'enabled again afterwards')
})
