import { check, DESKTOP, PHONES, sidewaysOverflow } from '../harness.mjs'

await check('mobile-new-document', async (h) => {
  for (const device of [...PHONES, DESKTOP]) {
    const narrow = device !== DESKTOP

    h.step(`${device.name}: documents list`)
    let page = await h.open('/documents', device)
    await page.waitForSelector('.documents-list tbody tr')
    const columns = await page.locator('.documents-list th:visible').count()
    h.expect(
      columns === (narrow ? 4 : 6),
      `[${device.name}] visible columns`,
      `${columns}`,
    )
    h.expectNone(
      await sidewaysOverflow(page),
      `[${device.name}] list: no sideways scroll`,
    )
    await h.screenshot(page, `list-${device.name}`)

    h.step(`${device.name}: new document form`)
    page = await h.open('/new', device)
    await page.waitForSelector('.new-document-form')
    h.expectNone(
      await sidewaysOverflow(page),
      `[${device.name}] form: no sideways scroll`,
    )
    const box = await page
      .locator('.new-document-form button[type=submit]')
      .boundingBox()
    h.expect(
      box.height >= 44 || !narrow,
      `[${device.name}] submit is 44px tall`,
      `${box.height}`,
    )
    await h.screenshot(page, `form-${device.name}`)
  }
})
