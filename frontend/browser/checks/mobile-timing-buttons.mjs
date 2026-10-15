// Step 7 of docs/completed/mobile.md: on touch, in timing mode, the player bar
// carries nudge −/+ and Stamp, which do what ←/→ and / do.
import {
  check,
  DESKTOP,
  PHONES,
  playerReady,
  sidewaysOverflow,
  smallTapTargets,
  tapOrClick,
  tokenized,
} from '../harness.mjs'

await check('mobile-timing-buttons', async (h) => {
  const path = `/documents/${await h.videoDocument({ untimed: true })}`
  const bar = '.player-controls'

  async function startTiming(page) {
    await tokenized(page)
    await playerReady(page)
    await tapOrClick(page, page.getByRole('button', { name: 'Edit timings' }))
    await page.waitForSelector('.timing-row')
  }
  const picked = (page) =>
    page.$eval('.timing-row.selected', (el) => ({
      index: [...el.parentElement.children].indexOf(el),
      time: el.querySelector('.timing-gutter span').textContent,
    }))

  for (const device of PHONES) {
    const tag = `[${device.name}]`
    h.step(`${device.name}: the bar in timing mode`)
    const page = await h.open(path, device)
    await startTiming(page)

    const tops = await page.$$eval(`${bar} button`, (els) =>
      els
        .filter((el) => el.offsetWidth > 0)
        .map((el) => ({
          clipped: el.scrollWidth > el.clientWidth,
          label: el.getAttribute('aria-label') ?? el.textContent,
          row: el.closest('.player-timing')
            ? '.player-timing'
            : '.player-transport',
          top: el.getBoundingClientRect().top,
          right: el.getBoundingClientRect().right,
        })),
    )
    const rows = (selector) => tops.filter(({ row }) => row === selector)
    const sameRow = (buttons) =>
      buttons.every(({ top }) => Math.abs(top - buttons[0].top) <= 1)
    const transport = rows('.player-transport')
    const timing = rows('.player-timing')
    h.expect(
      transport.length === 3 &&
        timing.length === 3 &&
        sameRow(transport) &&
        sameRow(timing) &&
        timing[0].top > transport[0].top &&
        tops.every(({ clipped }) => !clipped) &&
        tops.every(({ right }) => right <= device.options.viewport.width),
      `${tag} playback and timing buttons in two rows, Video gone`,
      JSON.stringify(tops),
    )
    h.expectNone(
      await smallTapTargets(page, '.player-bar'),
      `${tag} the bar's buttons are 44px tap targets`,
    )
    h.expectNone(await sidewaysOverflow(page), `${tag} no sideways scroll`)

    const nudgeLater = page.locator(`${bar} [aria-label="Nudge later"]`)
    // canNudge reaches the bar a render after the line's time changes.
    h.expect(
      await nudgeLater
        .and(page.locator(':disabled'))
        .waitFor({ timeout: 2000 })
        .then(
          () => true,
          () => false,
        ),
      `${tag} Nudge is disabled while the picked line has no time`,
    )

    // Focus stays where it was, so Space still plays and pauses.
    const stamp = page.locator(`${bar} .timing-stamp`)
    await tapOrClick(page, stamp)
    h.expect(
      await page.evaluate(() => document.activeElement === document.body),
      `${tag} Stamp doesn't take focus`,
    )
    const stamped = await picked(page)
    h.expect(
      stamped.time !== 'untimed',
      `${tag} Stamp times a line`,
      JSON.stringify(stamped),
    )
    h.expect(
      await nudgeLater
        .and(page.locator(':enabled'))
        .waitFor({ timeout: 2000 })
        .then(
          () => true,
          () => false,
        ),
      `${tag} Nudge is enabled once the picked line has a time`,
    )
    await tapOrClick(page, nudgeLater)
    h.expect(
      (await page.locator('.timing-row.selected .nudged').count()) === 1,
      `${tag} the nudged line's time is highlighted`,
    )
    const nudged = await picked(page)
    h.expect(
      nudged.index === stamped.index && nudged.time > stamped.time,
      `${tag} Nudge later moves the picked line's start`,
      JSON.stringify({ stamped, nudged }),
    )
    await h.screenshot(page, `timing-${device.name}`, { fullPage: false })
  }

  h.step('desktop: same key, same result')
  const desk = await h.open(path, DESKTOP)
  await startTiming(desk)
  h.expect(
    (await desk.locator(`${bar} .timing-stamp`).count()) === 0,
    'no timing buttons with a mouse',
  )
  await desk.keyboard.press('/')
  await desk.waitForSelector('.timing-row.selected:not(.untimed)')
  const stamped = await picked(desk)
  await desk.keyboard.press('ArrowRight')
  await desk.waitForSelector('.timing-row.selected .nudged')
  const nudged = await picked(desk)
  h.expect(
    stamped.time !== 'untimed' &&
      nudged.index === stamped.index &&
      nudged.time > stamped.time,
    '/ then → give what Stamp then Nudge later give on the phone',
    JSON.stringify({ stamped, nudged }),
  )
})
