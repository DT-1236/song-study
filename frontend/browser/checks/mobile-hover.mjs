// Step 5a of docs/mobile.md: hover only from a mouse, no sticky :hover on
// touch, and the "Pinned" marker in a pinned gloss on every device.
import {
  check,
  DESKTOP,
  PHONE,
  isShown,
  settle,
  token,
  tokenized,
} from '../harness.mjs'

const before = (loc) =>
  loc.evaluate((el) => getComputedStyle(el, '::before').backgroundColor)

await check('mobile-hover', async (h) => {
  const path = `/documents/${h.seed.document_id}`
  const surface = '蜘蛛'

  h.step('phone: tap twice')
  const phone = await h.open(path, PHONE)
  await tokenized(phone)
  const tok = await token(phone, surface)
  const resting = await before(tok)
  await tok.tap()
  h.expect(await isShown(phone, '.gloss-popup'), 'a tap opens the gloss')
  h.expect(
    (await phone.locator('.gloss-pinned').count()) === 1,
    'a tapped (pinned) gloss shows the marker',
  )
  await tok.tap()
  await settle(phone)
  h.expect(!(await isShown(phone, '.gloss-popup')), 'a second tap closes it')
  h.expect(
    (await before(tok)) === resting,
    'the token has no sticky :hover highlight',
  )

  h.step('desktop: hover, cross into popup, click, click')
  const desk = await h.open(path, DESKTOP)
  await tokenized(desk)
  const dtok = await token(desk, surface)
  await dtok.hover()
  await desk.waitForSelector('.gloss-popup')
  h.expect(
    (await desk.locator('.gloss-pinned').count()) === 0,
    'a hovered popup has no marker',
  )
  const popup = await desk.locator('.gloss-popup').boundingBox()
  await desk.mouse.move(popup.x + popup.width / 2, popup.y + 10, { steps: 8 })
  await desk.waitForTimeout(300) // longer than the 150ms grace period
  h.expect(
    await isShown(desk, '.gloss-popup'),
    'moving into the popup keeps it open',
  )
  await dtok.click()
  await settle(desk)
  h.expect(
    (await desk.locator('.gloss-pinned').count()) === 1,
    'a click pins it and the marker appears',
  )
  await dtok.click()
  await desk.mouse.move(5, 5)
  await desk.waitForTimeout(300)
  h.expect(!(await isShown(desk, '.gloss-popup')), 'a second click unpins it')
})
