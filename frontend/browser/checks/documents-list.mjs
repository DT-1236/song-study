import { check, DESKTOP, PHONE, isShown } from '../harness.mjs'

// Clicking a document in the list opens its page at once, showing the lyrics
// as written while they process, and then the processed ones in their place.
await check('documents-list', async (h) => {
  const seeded = await h.api('GET', `/documents/${h.seed.document_id}`)
  const lyrics = seeded.text.split('\n')[0]

  for (const device of [PHONE, DESKTOP]) {
    h.step(`${device.name}: create a document with no tokens`)
    const title = `List check ${device.name} ${Date.now()}`
    await h.api('POST', '/documents', { title, text: lyrics })

    const page = await h.open('/documents', device)
    // Holds the tokens back until the processing state has been looked at.
    let release
    const released = new Promise((resolve) => (release = resolve))
    await h.stub(
      page,
      /\/api\/documents\/\d+\/tokens(\/processing)?$/,
      () => released,
    )

    h.step(`${device.name}: click its row`)
    await page.click(`tr.clickable-row:has-text("${title}")`)
    await page.waitForURL(/\/documents\/\d+$/)
    await page.waitForSelector('.processing-note')
    h.expect(
      await isShown(page, '.processing-note .spinner'),
      `[${device.name}] opens the page while it processes`,
    )
    const plain = await page.locator('#lyrics .synced-lyrics').innerText()
    h.expect(
      plain.includes(lyrics.trim()),
      `[${device.name}] shows the lyrics as written`,
    )

    h.step(`${device.name}: once processed`)
    release()
    await page.waitForSelector('.processing-note', { state: 'detached' })
    h.expect(
      (await page.locator('#lyrics ruby').count()) > 0,
      `[${device.name}] replaces them with the furigana'd lyrics`,
    )
  }
})
