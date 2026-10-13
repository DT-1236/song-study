// Step 5b of docs/ongoing/mobile.md: on touch, a tap previews a gloss and a
// long press pins it, with a countdown ring; a tap or swipe elsewhere closes
// a preview but not a pin; and the gloss opens as a sheet at the bottom of
// the screen.
import {
  center,
  check,
  finger,
  isShown,
  NARROW,
  PHONE,
  playerReady,
  settle,
  sidewaysOverflow,
  smallInputFonts,
  smallTapTargets,
  token,
  tokenized,
} from '../harness.mjs'

// LONG_PRESS_MS in DocumentViewPage.
const LONG_PRESS_MS = 500

const before = (loc) =>
  loc.evaluate((el) => getComputedStyle(el, '::before').backgroundColor)
const ring = (loc) =>
  loc.evaluate((el) => getComputedStyle(el, '::after').backgroundImage)
const isOpen = (page) => isShown(page, '.gloss-popup')
const isPinned = async (page) =>
  (await page.locator('.gloss-popup .gloss-pinned').count()) === 1
// The surface of the token whose gloss is open, or null.
const openSurface = (page) =>
  page.evaluate(() => {
    const popup = document.querySelector('.gloss-popup')
    if (!popup) return null
    const copy = popup.parentElement.cloneNode(true)
    copy.querySelectorAll('rt, .gloss-popup').forEach((n) => n.remove())
    return copy.textContent
  })
const rect = (page, selector) =>
  page.$eval(selector, (el) => {
    const r = el.getBoundingClientRect()
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }
  })
// A point on screen over the lyrics box itself, between the top bar and the
// sheet (or the player bar), at least CLEAR px from anything else: a touch
// lands on something clickable up to about 8px away, as on a phone. The
// lowest found, so a swipe from it has room.
const blankPoint = (page) =>
  page.evaluate(() => {
    const CLEAR = 12
    const box = document.querySelector('.lyrics-box')
    const isBox = (x, y) => document.elementFromPoint(x, y) === box
    const r = box.getBoundingClientRect()
    const low = Math.min(
      innerHeight,
      document.querySelector('.gloss-sheet')?.getBoundingClientRect().top ??
        Infinity,
      document.querySelector('.player-bar')?.getBoundingClientRect().top ??
        Infinity,
    )
    const high = document
      .querySelector('.top-bar')
      .getBoundingClientRect().bottom
    for (let y = Math.min(r.bottom, low) - CLEAR; y > high + CLEAR; y -= 2)
      for (let x = r.right - CLEAR; x > r.left + CLEAR; x -= 2)
        if (
          isBox(x, y) &&
          isBox(x - CLEAR, y) &&
          isBox(x + CLEAR, y) &&
          isBox(x, y - CLEAR) &&
          isBox(x, y + CLEAR)
        )
          return { x, y }
    return null
  })
const scrollTop = (page) => page.$eval('.content', (el) => el.scrollTop)
// Waits until the lyrics have scrolled from `top`, as playback moves the
// line being sung.
const scrolledFrom = (page, top) =>
  page.waitForFunction(
    (top) => document.querySelector('.content').scrollTop !== top,
    top,
    { timeout: 20_000, polling: 250 },
  )
// Swipes from `point` and says whether the lyrics scrolled: back toward the
// top, which has room once they're scrolled at all (closing a sheet takes
// its room away from the end).
const swipeScrolls = async (page, f, point) => {
  const top = await scrollTop(page)
  await f.swipe(point.x, point.y, 120)
  return (await scrollTop(page)) < top
}

await check('mobile-gloss-sheet', async (h) => {
  const id = await h.videoDocument()
  // Each lyric line a second long, from the start, so playback moves the
  // line being sung down the lyrics quickly.
  const { text } = await h.api('GET', `/documents/${id}`)
  const lines = text
    .split('\n')
    .map((line, i) => (line.trim() ? { start: i, end: i + 1 } : null))
  await h.api('PUT', `/documents/${id}/timings`, { text, lines })
  const path = `/documents/${id}`

  h.step('phone: a tap previews')
  const page = await h.open(path, PHONE)
  await tokenized(page)
  const f = await finger(page)
  // Holds `locator` long enough to pin it.
  const holdOn = async (locator) => {
    const at = await center(locator)
    await f.hold(at.x, at.y, LONG_PRESS_MS * 1.5)
  }
  const spider = await token(page, '蜘蛛')
  const resting = await before(spider)
  await spider.tap()
  await settle(page)
  h.expect(await isOpen(page), 'a tap opens the gloss')
  h.expect(!(await isPinned(page)), 'a preview has no Pinned marker')
  const sheet = await rect(page, '.gloss-popup')
  const bar = await rect(page, '.player-bar')
  h.expect(
    (await page.$eval(
      '.gloss-popup',
      (el) => getComputedStyle(el).position,
    )) === 'fixed' &&
      sheet.left === 0 &&
      sheet.right === 390 &&
      Math.abs(sheet.bottom - bar.top) <= 1,
    'the gloss is a full-width sheet directly above the player bar',
    JSON.stringify({ sheet, bar }),
  )
  const tok = await spider.boundingBox()
  h.expect(
    tok.y + tok.height <= sheet.top + 0.5 &&
      tok.y >= (await rect(page, '.top-bar')).bottom,
    'the outlined token is in view, above the sheet',
    JSON.stringify({ tok, sheet }),
  )
  h.expect(
    await page.locator('.gloss-hold-hint').isVisible(),
    'the preview says a hold pins',
  )
  h.expectNone(
    await smallTapTargets(page, '.gloss-sheet-header'),
    'the sheet header passes the tap-target check',
  )
  await h.screenshot(page, 'preview')
  await spider.tap()
  await settle(page)
  h.expect(!(await isOpen(page)), 'a second tap on the token closes it')
  h.expect(
    (await before(spider)) === resting,
    'the token has no sticky highlight',
  )

  h.step('phone: switching and dismissing a preview')
  await spider.tap()
  const thread = await token(page, '糸')
  await thread.tap()
  h.expect(
    (await openSurface(page)) === '糸',
    'a tap on another token switches',
  )
  let blank = await blankPoint(page)
  await page.touchscreen.tap(blank.x, blank.y)
  h.expect(!(await isOpen(page)), 'a tap on blank lyrics space closes it')
  await thread.tap()
  h.expect(
    (await swipeScrolls(page, f, await blankPoint(page))) &&
      !(await isOpen(page)),
    'a swipe starting on blank space scrolls and closes it',
  )
  await thread.tap()
  h.expect(
    (await swipeScrolls(page, f, await center(spider))) &&
      !(await isOpen(page)),
    'a swipe starting on a token scrolls and closes it',
  )

  h.step('phone: what leaves a preview open')
  // 事 has more senses than are listed before Show more.
  const koto = await token(page, '事')
  await koto.tap()
  await page.locator('.gloss-popup .gloss-show-more').tap()
  await page.locator('.gloss-popup .more-options > summary').tap()
  h.expect(
    (await openSurface(page)) === '事',
    'taps on Show more and More options leave it open',
  )
  const overflowing = await page.$eval(
    '.gloss-popup',
    (el) => el.scrollHeight > el.clientHeight,
  )
  h.expect(overflowing, 'the expanded gloss scrolls inside the sheet')
  const inside = await rect(page, '.gloss-popup')
  let top = await scrollTop(page)
  await f.swipe(inside.left + 40, inside.bottom - 20, -400)
  await settle(page)
  h.expect(
    (await isOpen(page)) &&
      (await page.$eval('.gloss-popup', (el) => el.scrollTop)) > 0 &&
      (await scrollTop(page)) === top,
    'scrolling the gloss past its end leaves it open and the lyrics still',
  )
  await page.locator('.gloss-popup .gloss-close').tap()
  // 犍陀 has no dictionary entry under its reading, so its gloss offers to
  // correct the reading.
  await (await token(page, '犍陀')).tap()
  const fix = page.locator('.gloss-popup .reading-correction input')
  if (!(await fix.isVisible()))
    await page.locator('.gloss-popup .more-options > summary').tap()
  await fix.scrollIntoViewIfNeeded()
  await fix.tap()
  h.expect(
    (await isOpen(page)) &&
      (await fix.evaluate((el) => el === document.activeElement)),
    'focusing the reading-fix input leaves it open',
  )
  h.expectNone(await smallInputFonts(page), 'the sheet has no input under 16px')
  await h.screenshot(page, 'long-gloss')
  await page.locator('.gloss-popup .gloss-close').tap()
  h.expect(!(await isOpen(page)), 'Close closes a preview')

  h.step('phone: a long press pins')
  const kumo2 = await token(page, '蜘蛛', 1)
  let at = await center(kumo2)
  await f.down(at.x, at.y)
  await page.waitForTimeout(LONG_PRESS_MS / 2)
  h.expect(
    (await ring(kumo2)).startsWith('conic-gradient'),
    'halfway through a hold, the countdown ring shows',
  )
  await page.waitForTimeout(LONG_PRESS_MS)
  await f.up()
  await settle(page)
  h.expect(
    (await openSurface(page)) === '蜘蛛' && (await isPinned(page)),
    'after the hold the gloss is pinned, with the marker',
  )
  h.expect((await ring(kumo2)) === 'none', 'the ring goes once the pin lands')
  h.expect(
    !(await page.locator('.gloss-hold-hint').isVisible()),
    'the hint goes once a hold has pinned',
  )
  h.expect(
    (await swipeScrolls(page, f, await blankPoint(page))) &&
      (await isPinned(page)),
    'a swipe on the lyrics leaves a pin open',
  )
  blank = await blankPoint(page)
  await page.touchscreen.tap(blank.x, blank.y)
  h.expect(await isPinned(page), 'a tap on blank space leaves a pin open')
  await thread.tap()
  h.expect(
    (await openSurface(page)) === '糸' && !(await isPinned(page)),
    'the next tap on another token previews it: nothing swallowed it',
  )
  await holdOn(thread)
  h.expect(await isPinned(page), 'holding the previewed token pins it')
  await thread.tap()
  h.expect(!(await isOpen(page)), 'a tap on the pinned token closes it')
  await holdOn(thread)
  await page.locator('.gloss-popup .gloss-close').tap()
  h.expect(!(await isOpen(page)), 'Close closes a pin')

  h.step('phone: a hold low on the screen')
  // The sheet opens under the finger still holding the token, so a click
  // the release sends would land on whatever in the sheet is there. Held
  // well past the pin: Chromium sends that click only after a longer hold.
  // Counts clicks on the sheet that went through, as read once they've
  // been dispatched: the gloss stops its own clicks' propagation, so a
  // listener later in the event's path wouldn't see them at all.
  await page.evaluate(() => {
    window.sheetClicks = 0
    window.addEventListener(
      'click',
      (e) => {
        if (!e.target.closest?.('.gloss-popup')) return
        setTimeout(() => {
          if (!e.defaultPrevented) window.sheetClicks++
        })
      },
      true,
    )
  })
  const low = await page.evaluate(() => {
    const barTop = document
      .querySelector('.player-bar')
      .getBoundingClientRect().top
    return [...document.querySelectorAll('.lyrics-box .token')].findIndex(
      (el) => {
        const r = el.getBoundingClientRect()
        return (
          el.classList.contains('has-gloss') &&
          r.top > innerHeight * 0.6 &&
          r.bottom < barTop - 8
        )
      },
    )
  })
  at = await center(page.locator('.lyrics-box .token').nth(low))
  await f.down(at.x, at.y)
  await page.waitForTimeout(LONG_PRESS_MS * 3)
  const under = await page.evaluate(
    ({ x, y }) => !!document.elementFromPoint(x, y)?.closest('.gloss-popup'),
    at,
  )
  await f.up()
  await settle(page)
  h.expect(under, 'the pinned sheet opened under the finger')
  h.expect(
    (await isPinned(page)) &&
      (await page.evaluate(() => window.sheetClicks)) === 0,
    "the hold's release clicks nothing in the sheet",
  )
  await page.locator('.gloss-popup .gloss-close').tap()

  h.step('phone: cancelled presses')
  at = await center(kumo2)
  await f.down(at.x, at.y)
  await f.move(at.x + 20, at.y)
  await page.waitForTimeout(LONG_PRESS_MS * 1.5)
  h.expect(
    (await ring(kumo2)) === 'none',
    'a press that moves 20px loses its ring',
  )
  await f.up()
  h.expect(!(await isPinned(page)), 'and pins nothing')
  at = await center(kumo2)
  await f.down(at.x, at.y)
  await page.waitForTimeout(LONG_PRESS_MS / 3)
  await f.up()
  h.expect(
    (await ring(kumo2)) === 'none' && !(await isPinned(page)),
    'a press released early pins nothing and leaves no ring',
  )
  // That was a tap: kumo2's preview is open.
  const sense = page.locator('.gloss-popup .gloss-senses li').first()
  at = await center(sense)
  await f.down(at.x, at.y)
  await page.waitForTimeout(LONG_PRESS_MS / 2)
  const ringInSheet = await ring(kumo2)
  await page.waitForTimeout(LONG_PRESS_MS)
  await f.up()
  h.expect(
    ringInSheet === 'none' && (await isOpen(page)) && !(await isPinned(page)),
    'a hold on text in the sheet runs no ring and changes no pin',
  )

  h.step('phone: the sheet and the end of the lyrics')
  await page.$eval('.content', (el) => (el.scrollTop = el.scrollHeight))
  const last = await page.evaluate(() => {
    const tokens = [...document.querySelectorAll('.lyrics-box .token')].filter(
      (el) => el.textContent.trim(),
    )
    return tokens[tokens.length - 1].getBoundingClientRect().bottom
  })
  h.expect(
    (await isOpen(page)) && last <= (await rect(page, '.gloss-popup')).top,
    'the last lyric line scrolls above the sheet',
  )
  await page.locator('.gloss-popup .gloss-close').tap()

  h.step('phone: the hint stays gone after a reload')
  await page.reload()
  await tokenized(page)
  await (await token(page, '糸')).tap()
  h.expect(
    (await isOpen(page)) &&
      !(await page.locator('.gloss-hold-hint').isVisible()),
    'no hint after a reload once a hold has pinned',
  )

  h.step('phone: playback')
  await playerReady(page)
  await page.locator('.player-video-toggle').tap()
  await (await token(page, '蜘蛛')).tap()
  await settle(page)
  const lineHeight = await page.$eval('.lyrics-box', (el) =>
    parseFloat(getComputedStyle(el).lineHeight),
  )
  const shown = await rect(page, '.gloss-popup')
  const topBar = await rect(page, '.top-bar')
  h.expect(
    shown.top - topBar.bottom >= 3 * lineHeight - 1,
    'with the video shown, three lyric lines fit above the sheet',
    JSON.stringify({ shown, topBar, lineHeight }),
  )
  await h.screenshot(page, 'video-shown')
  await page.locator('.player-video-toggle').tap()
  top = await scrollTop(page)
  await page.locator('.player-controls button[aria-label="Play"]').tap()
  await scrolledFrom(page, top)
  h.expect(
    await isOpen(page),
    "the playing line's auto-scroll leaves a preview open",
  )
  await page.locator('.gloss-popup .gloss-close').tap()
  await holdOn(await token(page, '蜘蛛', 2))
  // The pin's own scroll into view, then the line being sung moving on.
  top = await scrollTop(page)
  await scrolledFrom(page, top)
  // Its first token: auto-scroll keeps where the line starts in view, even
  // when it wraps.
  const playing = await page.$eval(
    '.token.playing',
    (el) => el.getBoundingClientRect().bottom,
  )
  h.expect(
    (await isPinned(page)) &&
      playing <= (await rect(page, '.gloss-popup')).top + 0.5,
    'with a gloss pinned, the line being sung stays above the sheet',
    JSON.stringify({ playing }),
  )
  await page.locator('.player-controls button[aria-label="Pause"]').tap()

  h.step('narrow: the sheet fits 320px')
  const narrow = await h.open(path, NARROW)
  await tokenized(narrow)
  await (await token(narrow, '蜘蛛')).tap()
  await settle(narrow)
  const thin = await rect(narrow, '.gloss-popup')
  h.expect(
    thin.left === 0 && thin.right === 320,
    'the sheet spans the 320px screen',
  )
  h.expectNone(await sidewaysOverflow(narrow), 'no sideways scroll')
  h.expectNone(
    await smallTapTargets(narrow, '.gloss-sheet-header'),
    'the sheet header passes the tap-target check',
  )
  await h.screenshot(narrow, 'preview')
})
