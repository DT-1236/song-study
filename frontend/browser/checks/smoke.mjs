// That the harness works end to end: the seeded document lists, opens, and
// shows a gloss, on the desktop and on a phone. Run it first when a check
// fails in a way that doesn't look like the change under test.
import {
  check,
  DESKTOP,
  PHONE,
  isShown,
  token,
  tokenized,
} from '../harness.mjs'

await check('smoke', async (h) => {
  const documentPath = `/documents/${h.seed.document_id}`

  h.step('documents list (desktop)')
  const list = await h.open('/documents', DESKTOP)
  await list.waitForSelector('.clickable-row')
  h.expect(
    (await list.locator('.clickable-row').count()) >= 1,
    'the seeded document is listed',
  )

  h.step('document page (desktop)')
  const page = await h.open(documentPath, DESKTOP)
  await tokenized(page)
  const word = await token(page, '蜘蛛')
  await word.hover()
  await page.waitForSelector('.gloss-popup')
  h.expect(await isShown(page, '.gloss-popup'), 'hovering 蜘蛛 shows its gloss')
  await h.screenshot(page, 'document', { fullPage: false })

  h.step('document page (phone)')
  const phone = await h.open(documentPath, PHONE)
  await tokenized(phone)
  h.expect(await isShown(phone, '.top-bar'), 'the top bar shows on a phone')
  await h.screenshot(phone, 'document', { fullPage: false })
})
