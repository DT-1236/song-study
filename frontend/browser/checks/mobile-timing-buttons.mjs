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
  const path = `/documents/${await h.videoDocument()}`
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
          top: el.getBoundingClientRect().top,
          right: el.getBoundingClientRect().right,
        })),
    )
    h.expect(
      tops.length === 6 &&
        tops.every(({ top }) => Math.abs(top - tops[0].top) <= 1) &&
        tops.every(({ clipped }) => !clipped) &&
        tops.every(({ right }) => right <= device.options.viewport.width),
      `${tag} six buttons share one row, Video gone`,
      JSON.stringify(tops),
    )
    h.expectNone(
      await smallTapTargets(page, '.player-bar'),
      `${tag} the bar's buttons are 44px tap targets`,
    )
    h.expectNone(await sidewaysOverflow(page), `${tag} no sideways scroll`)

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
    await tapOrClick(page, page.locator(`${bar} [aria-label="Nudge later"]`))
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
  const stamped = await picked(desk)
  await desk.keyboard.press('ArrowRight')
  const nudged = await picked(desk)
  h.expect(
    stamped.time !== 'untimed' &&
      nudged.index === stamped.index &&
      nudged.time > stamped.time,
    '/ then → give what Stamp then Nudge later give on the phone',
    JSON.stringify({ stamped, nudged }),
  )
})
