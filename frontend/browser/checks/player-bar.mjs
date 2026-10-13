// The player bar docked at the bottom of the document page: a hidden video
// that still plays, buttons that do what Space, , and . do and look pressed
// when those keys are, and a Video toggle kept across reloads.
import {
  BASE,
  check,
  DESKTOP,
  PHONE,
  playerReady,
  sidewaysOverflow,
  smallTapTargets,
  tapOrClick,
  videoFrame,
  videoTime,
  tokenized,
} from '../harness.mjs'

await check('player-bar', async (h) => {
  const path = `/documents/${await h.videoDocument()}`

  // Waits until the video has played past `seconds`.
  const playedPast = async (page, seconds) => {
    const frame = await videoFrame(page)
    await frame.waitForFunction(
      (s) => document.querySelector('video').currentTime > s,
      seconds,
      // Not on animation frames, the default: a hidden frame gets none.
      { timeout: 15_000, polling: 250 },
    )
  }
  const button = (page, label) =>
    page.locator(`.player-controls button[aria-label="${label}"]`)
  const isPressed = (page, label) =>
    button(page, label).evaluate((el) => el.classList.contains('pressed'))

  for (const device of [DESKTOP, PHONE]) {
    const tag = `[${device.name}]`
    h.step(`${device.name}: hidden video plays from the bar`)
    const page = await h.open(path, device)
    await tokenized(page)
    await playerReady(page)
    const box = await page.$eval('.youtube-player', (el) => {
      const r = el.getBoundingClientRect()
      return { width: r.width, height: r.height, hidden: el.inert }
    })
    h.expect(
      box.width === 200 && box.height === 200 && box.hidden,
      `${tag} the video is a hidden, inert 200x200 by default`,
      JSON.stringify(box),
    )
    const bar = await page.$eval('.player-bar', (el) => ({
      bottom: el.getBoundingClientRect().bottom,
      screen: el.closest('.content').getBoundingClientRect().bottom,
    }))
    h.expect(
      Math.abs(bar.bottom - bar.screen) <= 1,
      `${tag} the bar is docked at the bottom of the screen at scroll top`,
      JSON.stringify(bar),
    )
    const padding = await page.$eval('.player-bar', (el) => ({
      bar: el.offsetHeight,
      padding: parseFloat(
        getComputedStyle(el.closest('.content')).scrollPaddingBottom,
      ),
    }))
    h.expect(
      padding.bar > 0 && padding.padding === padding.bar,
      `${tag} what's scrolled into view stops above the bar`,
      JSON.stringify(padding),
    )
    h.expectNone(
      await smallTapTargets(page, '.player-bar'),
      `${tag} the bar's buttons are 44px tap targets`,
    )
    h.expectNone(await sidewaysOverflow(page), `${tag} no sideways scroll`)

    await tapOrClick(page, button(page, 'Play'))
    await playedPast(page, 1)
    h.expect(true, `${tag} Play plays the hidden video`)
    h.expect(
      (await button(page, 'Pause').count()) === 1,
      `${tag} the button turns to Pause`,
    )
    h.expect(
      await page.evaluate(() => document.activeElement === document.body),
      `${tag} the button didn't take focus`,
    )

    const before = await videoTime(page)
    await tapOrClick(page, button(page, 'Forward 3s'))
    const after = await videoTime(page)
    h.expect(
      after - before >= 2.5,
      `${tag} Forward seeks 3s`,
      `${before} → ${after}`,
    )
    await tapOrClick(page, button(page, 'Pause'))
    await page.waitForSelector('.player-controls button[aria-label="Play"]')
    h.expect(true, `${tag} Pause pauses`)
    await h.screenshot(page, 'hidden', { fullPage: false })
  }

  h.step('desktop: keys press the buttons')
  const desk = await h.open(path, DESKTOP)
  await tokenized(desk)
  await playerReady(desk)
  h.expect(
    await desk.$eval('.player-controls kbd', (el) => el.offsetWidth > 0),
    'the buttons show their keys',
  )
  await desk.keyboard.press('Period')
  h.expect(await isPressed(desk, 'Forward 3s'), '. presses Forward')
  await desk.waitForSelector('.player-controls button.pressed', {
    state: 'detached',
  })
  h.expect(true, 'and lets it go')
  await desk.keyboard.press('Space')
  h.expect(await isPressed(desk, 'Play'), 'Space presses Play')
  await playedPast(desk, 4)
  h.expect(true, 'and plays')
  await desk.keyboard.press('Space')

  h.step('desktop: the Video toggle')
  await desk.click('.player-video-toggle')
  const shown = await desk.$eval('.youtube-player', (el) => ({
    width: el.getBoundingClientRect().width,
    inert: el.inert,
  }))
  h.expect(
    shown.width >= 300 && !shown.inert,
    'Video shows the video',
    JSON.stringify(shown),
  )
  await h.screenshot(desk, 'shown', { fullPage: false })
  await desk.goto(BASE + path)
  await desk.waitForSelector('.player-bar')
  h.expect(
    await desk.$eval(
      '.player-video-toggle',
      (el) => el.getAttribute('aria-pressed') === 'true',
    ),
    'the choice is kept across a reload',
  )

  h.step('phone: no keys shown')
  const phone = await h.open(path, PHONE)
  await phone.waitForSelector('.player-bar')
  h.expect(
    await phone.$eval('.player-controls kbd', (el) => el.offsetWidth === 0),
    'the keys are hidden on touch',
  )
})
