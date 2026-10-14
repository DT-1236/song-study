// Step 3 of docs/completed/mobile.md: a disabled "Edit timings" says why as
// text, a line play button takes a 44px-wide tap without reaching its line's
// first token, and a shown video sits beside the bar's buttons in landscape
// without its iframe remounting.
import {
  check,
  isShown,
  PHONE,
  playerReady,
  rotate,
  tapOrClick,
  tokenized,
  videoFrame,
  videoTime,
} from '../harness.mjs'

// The plan's landscape phone, started in portrait so the check can rotate it.
const ROTATING = {
  name: 'rotating',
  options: {
    viewport: { width: 390, height: 664 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 3,
  },
}

await check('mobile-document-layout', async (h) => {
  // A document of the seed's text with every line timed, made on first use.
  // Line play buttons show only with a video, but timings saved on
  // videoDocument() would change what the other checks see, and a user's
  // video can be in one document only. So it gets a placeholder video ID:
  // its player never needs to load for a check of the buttons' tap area.
  const timedDocument = async () => {
    const title = 'Timed (mobile-document-layout)'
    const { items } = await h.api('GET', '/documents?page=1&page_size=100')
    const found = items.find((doc) => doc.title === title)
    if (found) return found.id
    const seeded = await h.api('GET', `/documents/${h.seed.document_id}`)
    const doc = await h.api('POST', '/documents', {
      title,
      text: seeded.text,
      youtube_video_id: 'placeholder',
    })
    const lines = doc.text
      .split('\n')
      .map((line, i) => (line.trim() ? { start: i * 3, end: i * 3 + 3 } : null))
    await h.api('PUT', `/documents/${doc.id}/timings`, {
      text: doc.text,
      lines,
    })
    return doc.id
  }

  h.step('phone: a disabled Edit timings says why')
  const plain = await h.open(`/documents/${h.seed.document_id}`, PHONE)
  await tokenized(plain)
  h.expect(
    await plain
      .getByRole('button', { name: 'Edit timings' })
      .evaluate((el) => el.disabled),
    'Edit timings is disabled without a video',
  )
  h.expect(
    (await isShown(plain, '.edit-timings-blocker')) &&
      (await plain.textContent('.edit-timings-blocker')) === 'Needs a video',
    'its reason shows as text',
  )

  h.step('phone: line play tap area')
  const phone = await h.open(`/documents/${await timedDocument()}`, PHONE)
  await tokenized(phone)
  await phone.waitForSelector('.lyrics-box .line-play')
  await phone.$eval('.lyrics-box', (el) => el.scrollIntoView())
  const taps = await phone.$$eval('.lyrics-box .line-play', (buttons) => {
    const at = (button, x, y) => {
      const found = document.elementFromPoint(x, y)
      return found === button || button.contains(found)
    }
    // Only the buttons on screen and clear of the bar and the top bar, since
    // a hit test anywhere else finds what's on top.
    const onScreen = buttons.filter((button) => {
      const rect = button.getBoundingClientRect()
      return at(button, rect.left + rect.width / 2, rect.top + rect.height / 2)
    })
    return onScreen.map((button) => {
      const rect = button.getBoundingClientRect()
      const hits = (x) => at(button, x, rect.top + rect.height / 2)
      // The first token after the button, in the same line.
      let first = button.nextElementSibling
      while (first && !first.classList.contains('token')) {
        first = first.nextElementSibling
      }
      const token = first?.getBoundingClientRect()
      return {
        width: Math.round(rect.width),
        overlay: getComputedStyle(button, '::after').width,
        // 2px in from the overlay's left edge, and the button's own right edge.
        leftEdge: hits(rect.right - 42),
        rightEdge: hits(rect.right - 1),
        // The token's own center still belongs to the token.
        tokenFree:
          token === undefined ||
          !hits(token.left + Math.min(token.width / 2, 10)),
      }
    })
  })
  h.expect(
    taps.length > 0,
    'the timed document shows line play buttons on screen',
    `${taps.length} measured`,
  )
  h.expectNone(
    taps
      .map((tap, i) => ({ ...tap, i }))
      .filter(
        (tap) => tap.overlay !== '44px' || !tap.leftEdge || !tap.rightEdge,
      )
      .map((tap) => `line ${tap.i}: ${JSON.stringify(tap)}`),
    'a line play button takes taps across 44px',
  )
  h.expectNone(
    taps
      .map((tap, i) => ({ ...tap, i }))
      .filter((tap) => !tap.tokenFree)
      .map((tap) => `line ${tap.i}`),
    "its tap area doesn't reach the line's first token",
  )
  await h.screenshot(phone, 'line-play', { fullPage: false })

  h.step('portrait: show the video and play it')
  const page = await h.open(`/documents/${await h.videoDocument()}`, ROTATING)
  await tokenized(page)
  await playerReady(page)
  await tapOrClick(page, page.locator('.player-video-toggle'))
  await page.waitForSelector('.youtube-player:not(.hidden)')
  await tapOrClick(
    page,
    page.locator('.player-controls button[aria-label="Play"]'),
  )
  const frame = await videoFrame(page)
  await frame.waitForFunction(
    () => document.querySelector('video').currentTime > 1,
    null,
    { timeout: 15_000, polling: 250 },
  )
  const iframe = await page.$('iframe[src*="youtube"]')
  const layout = () =>
    page.evaluate(() => {
      const video = document
        .querySelector('.player-bar .youtube-player')
        .getBoundingClientRect()
      const controls = document
        .querySelector('.player-bar .player-controls')
        .getBoundingClientRect()
      return {
        share: video.width / innerWidth,
        beside:
          video.right <= controls.left &&
          video.top < controls.bottom &&
          controls.top < video.bottom,
      }
    })
  const portrait = await layout()
  h.expect(
    !portrait.beside,
    'in portrait the video is above the buttons',
    JSON.stringify(portrait),
  )

  // Whether `iframe` is still the page's player, and the video still plays.
  const sameAndPlaying = async (tag) => {
    h.expect(
      await iframe.evaluate(
        (el) => el.isConnected && el === document.querySelector('iframe'),
      ),
      `${tag}: the iframe is the same node`,
    )
    const before = await videoTime(page)
    await frame.waitForFunction(
      (t) => document.querySelector('video').currentTime > t + 0.5,
      before,
      { timeout: 10_000, polling: 250 },
    )
    h.expect(true, `${tag}: the video is still playing`)
  }

  h.step('landscape: the video beside the buttons')
  await rotate(page)
  const landscape = await layout()
  h.expect(
    landscape.beside && Math.abs(landscape.share - 0.4) < 0.02,
    'the video is beside the buttons at 40% of the width',
    JSON.stringify(landscape),
  )
  await sameAndPlaying('after rotating to landscape')
  await h.screenshot(page, 'landscape', { fullPage: false })

  h.step('portrait again')
  await rotate(page)
  h.expect(
    !(await layout()).beside,
    'back in portrait the video is above the buttons',
  )
  await sameAndPlaying('after rotating back')
})
