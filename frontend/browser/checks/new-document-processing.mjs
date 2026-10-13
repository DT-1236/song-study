import { check, DESKTOP, PHONE, isShown } from '../harness.mjs'

// Saving a new document opens it, showing its lyrics as written while their
// furigana and glosses process, and then the processed ones in their place.
await check('new-document-processing', async (h) => {
  const seeded = await h.api('GET', `/documents/${h.seed.document_id}`)
  // The seed's first paragraph, as a short document of its own.
  const lyrics = seeded.text.split('\n')[0]

  for (const device of [PHONE, DESKTOP]) {
    h.step(`${device.name}: save a new document`)
    const page = await h.open('/new', device)
    // Holds the tokens back until the processing state has been looked at:
    // the request starting their processing, and the polls after it.
    let release
    const released = new Promise((resolve) => (release = resolve))
    await page.route(
      /\/api\/documents\/\d+\/tokens(\/processing)?$/,
      async (route) => {
        await released
        await route.continue()
      },
    )
    await page.fill('#title', `Processing check ${device.name} ${Date.now()}`)
    await page.fill('#lyrics', lyrics)
    await page.click('.new-document-form button[type=submit]')
    await page.waitForURL(/\/documents\/\d+$/)
    h.expect(true, `[${device.name}] opens the new document`)

    h.step(`${device.name}: while processing`)
    await page.waitForSelector('.processing-note')
    h.expect(
      await isShown(page, '.processing-note .spinner'),
      `[${device.name}] shows a processing spinner`,
    )
    const plain = await page.locator('#lyrics .synced-lyrics').innerText()
    h.expect(
      plain.includes(lyrics.trim()),
      `[${device.name}] shows the lyrics as written`,
    )
    await h.screenshot(page, 'processing')

    h.step(`${device.name}: once processed`)
    release()
    await page.waitForSelector('.processing-note', { state: 'detached' })
    h.expect(
      (await page.locator('#lyrics .synced-lyrics').count()) === 0 &&
        (await page.locator('#lyrics ruby').count()) > 0,
      `[${device.name}] replaces them with the furigana'd lyrics`,
    )
    await h.screenshot(page, 'processed')
  }
})
