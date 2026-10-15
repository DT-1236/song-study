import { check } from '../harness.mjs'

// The Refresh button next to Unlink on a linked document: it disables after a
// refresh, and stays enabled across a reload until the server says a refresh
// is too soon. The harness backend can't reach LRCLIB, so the document is
// shown as linked and the refresh endpoint is stubbed.
await check('lrclib-refresh', async (h) => {
  const id = h.seed.document_id
  const linked = (doc) => ({
    ...doc,
    lrclib_uri: 'https://lrclib.net/api/get/1',
    lrclib_replaces_text: true,
  })
  let tooSoon = false
  let refreshes = 0

  // The linked document's page, opened with the stubs in place.
  const openLinked = async () => {
    const page = await h.open('/')
    await page.route(`**/api/documents/${id}`, async (route) => {
      const response = await route.fetch()
      await route.fulfill({ response, json: linked(await response.json()) })
    })
    await page.route(`**/api/documents/${id}/lrclib/refresh`, async (route) => {
      refreshes += 1
      if (tooSoon) {
        await route.fulfill({
          status: 429,
          json: {
            detail: 'Checked against LRCLIB a moment ago.',
            retry_after_seconds: 120,
          },
        })
      } else {
        await route.fulfill({
          json: linked(await h.api('GET', `/documents/${id}`)),
        })
      }
    })
    await page.goto(`/documents/${id}`)
    await page.getByRole('button', { name: 'Refresh' }).waitFor()
    return page
  }

  h.step('Refresh sits just before Unlink, enabled')
  const page = await openLinked()
  const refresh = page.getByRole('button', { name: 'Refresh' })
  h.expect(await refresh.isEnabled(), 'Refresh is enabled')
  const beside = await Promise.all([
    refresh.boundingBox(),
    page.getByRole('button', { name: 'Unlink' }).boundingBox(),
  ])
  h.expect(
    Math.abs(beside[0].y - beside[1].y) < 4 && beside[0].x < beside[1].x,
    'Refresh is beside Unlink, before it',
  )
  await h.screenshot(page, 'enabled')

  h.step('a refresh disables the button')
  await refresh.click()
  await page.waitForFunction(() =>
    [...document.querySelectorAll('button')].some(
      (b) => b.textContent === 'Refresh' && b.disabled,
    ),
  )
  h.expect(refreshes === 1, 'one refresh was sent', String(refreshes))
  await h.screenshot(page, 'disabled')

  h.step('after a reload it is enabled; a too-soon 429 disables it again')
  tooSoon = true
  const reloaded = await openLinked()
  const again = reloaded.getByRole('button', { name: 'Refresh' })
  h.expect(await again.isEnabled(), 'Refresh is enabled after a reload')
  await again.click()
  await reloaded.locator('.form-error', { hasText: 'a moment ago' }).waitFor()
  h.expect(await again.isDisabled(), 'Refresh is disabled by the 429')
  await h.screenshot(reloaded, 'too-soon')
})
