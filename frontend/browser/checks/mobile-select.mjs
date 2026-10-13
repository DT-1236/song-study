// Step 6 of docs/ongoing/mobile.md: a selection starts from the gloss's
// Select button, outlined instances are tapped into it, and on touch the
// selection panel is a sheet at the bottom of the screen that a swipe
// doesn't end.
import {
  center,
  check,
  DESKTOP,
  finger,
  isShown,
  PHONE,
  settle,
  sidewaysOverflow,
  smallTapTargets,
  token,
  tokenized,
} from '../harness.mjs'

const title = (page) =>
  page.locator('.selection-panel-title').textContent({ timeout: 2_000 })
const panelPosition = (page) =>
  page.$eval('.selection-panel', (el) => getComputedStyle(el).position)
const selectedCount = (page) => page.locator('.token.selected').count()

await check('mobile-select', async (h) => {
  const id = await h.videoDocument()
  const path = `/documents/${id}`

  h.step('phone: Select, then tap instances')
  const page = await h.open(path, PHONE)
  await tokenized(page)
  await (await token(page, '蜘蛛')).tap()
  await settle(page)
  await page.locator('.gloss-sheet .gloss-select').tap()
  await settle(page)
  h.expect(!(await isShown(page, '.gloss-popup')), 'Select closes the gloss')
  h.expect(
    (await panelPosition(page)) === 'fixed',
    'the selection panel is a sheet',
  )
  h.expect(
    (
      await page
        .locator('.selection-panel .conflict-note')
        .first()
        .textContent()
    ).startsWith('Tap'),
    'the hint says tap, not shift-click',
  )
  for (const nth of [1, 2]) {
    await (await token(page, '蜘蛛', nth)).tap()
    await settle(page)
  }
  h.expect(
    (await title(page)) === '3 × 蜘蛛 selected',
    `title: ${await title(page)}`,
  )
  const third = await token(page, '蜘蛛', 2)
  const tokenRect = await third.boundingBox()
  const sheetRect = await page.locator('.selection-panel').boundingBox()
  h.expect(
    tokenRect.y + tokenRect.height <= sheetRect.y + 1,
    'the last tapped token is above the sheet',
  )
  h.expectNone(await sidewaysOverflow(page), 'no sideways scroll')
  h.expectNone(
    await smallTapTargets(page, '.selection-panel .lyrics-header'),
    "the sheet's header passes the tap-target check",
  )
  await h.screenshot(page, 'selection-sheet')

  h.step('phone: what leaves a selection')
  const f = await finger(page)
  const at = await center(await token(page, '蜘蛛', 1))
  await f.swipe(at.x, at.y, -120)
  await settle(page)
  h.expect((await selectedCount(page)) === 3, 'a swipe leaves the selection')
  await page.locator('.selection-panel .lyrics-edit-toggle').tap()
  await settle(page)
  h.expect((await selectedCount(page)) === 0, 'Clear empties it')

  h.step('desktop: shift-click, click elsewhere, Escape, Select')
  const desk = await h.open(path, DESKTOP)
  await tokenized(desk)
  await (await token(desk, '蜘蛛')).click({ modifiers: ['Shift'] })
  await (await token(desk, '蜘蛛', 1)).click()
  h.expect((await selectedCount(desk)) === 2, 'shift-click then click selects')
  h.expect(
    (await panelPosition(desk)) === 'absolute',
    'the panel stays at the top on desktop',
  )
  // The lyrics box's own padding, beside the first line.
  await desk.locator('.lyrics-box').click({ position: { x: 3, y: 3 } })
  h.expect((await selectedCount(desk)) === 0, 'a click elsewhere clears')
  await (await token(desk, '蜘蛛')).click({ modifiers: ['Shift'] })
  await desk.keyboard.press('Escape')
  h.expect((await selectedCount(desk)) === 0, 'Escape clears')
  await (await token(desk, '蜘蛛')).click()
  await desk.locator('.gloss-popup .gloss-select').click()
  h.expect(
    (await selectedCount(desk)) === 1,
    'Select in a pinned popup selects',
  )
  await h.screenshot(desk, 'desktop-selection')
})
