// docs/mobile.md step 1, the responsive shell: on a narrow screen the side
// columns become drawers opened from a top bar; on a wide one nothing changes.
import {
  ALL_DEVICES,
  check,
  isShown,
  settle,
  sidewaysOverflow,
  smallInputFonts,
  smallTapTargets,
} from '../harness.mjs'

await check('mobile-shell', async (h) => {
  for (const device of ALL_DEVICES) {
    const name = device.name
    h.step(`${name}: /documents`)
    const page = await h.open('/documents', device)
    await page.waitForSelector('.app-layout')
    const narrow = await page.evaluate(
      () => matchMedia('(max-width: 900px), (max-height: 500px)').matches,
    )
    const inert = (selector) =>
      page.evaluate(
        (selector) => document.querySelector(selector).inert,
        selector,
      )
    const open = async (button) => {
      await page.locator('.top-bar button').nth(button).tap()
      await settle(page)
    }

    if (!narrow) {
      h.expect(!(await isShown(page, '.top-bar')), `[${name}] no top bar`)
      h.expect(
        (await isShown(page, '.sidebar')) &&
          (await isShown(page, '.right-panel')),
        `[${name}] both side columns shown`,
      )
      h.expect(
        !(await inert('.sidebar')) && !(await inert('.right-panel')),
        `[${name}] side columns not inert`,
      )
      await h.screenshot(page, 'documents', { fullPage: false })
      continue
    }

    h.expect(await isShown(page, '.top-bar'), `[${name}] top bar shown`)
    h.expect(
      (await inert('.sidebar')) && (await inert('.right-panel')),
      `[${name}] closed drawers are inert`,
    )
    h.expectNone(
      await smallTapTargets(page, '.top-bar'),
      `[${name}] top bar tap targets`,
    )
    h.expectNone(
      await sidewaysOverflow(page),
      `[${name}] no sideways scroll on /documents`,
    )

    h.step(`${name}: nav drawer`)
    await open(0)
    h.expect(
      (await isShown(page, '.sidebar')) && !(await inert('.sidebar')),
      `[${name}] menu opens the nav drawer`,
    )
    h.expectNone(
      await smallTapTargets(page, '.sidebar'),
      `[${name}] nav drawer tap targets`,
    )
    // Tap the backdrop beside the drawer, not under it.
    const { width } = page.viewportSize()
    await page
      .locator('.drawer-backdrop')
      .tap({ position: { x: width - 5, y: 200 } })
    await settle(page)
    h.expect(!(await isShown(page, '.sidebar')), `[${name}] backdrop closes it`)
    await open(0)
    await page.keyboard.press('Escape')
    await settle(page)
    h.expect(!(await isShown(page, '.sidebar')), `[${name}] Escape closes it`)
    await open(0)
    await page.locator('.sidebar a', { hasText: 'New Document' }).tap()
    await page.waitForURL('**/new')
    await settle(page)
    h.expect(
      !(await isShown(page, '.sidebar')),
      `[${name}] navigating closes it`,
    )
    h.expect(
      (await page.locator('.top-bar-title').textContent()) === 'New Document',
      `[${name}] top bar names the page`,
    )
    h.expectNone(
      await sidewaysOverflow(page),
      `[${name}] no sideways scroll on /new`,
    )

    h.step(`${name}: lookup drawer`)
    await open(1)
    h.expect(
      await isShown(page, '.right-panel'),
      `[${name}] Lookup opens the lookup drawer`,
    )
    h.expect(
      !(await isShown(page, '.sidebar')),
      `[${name}] only one drawer open`,
    )
    h.expect(
      await page.evaluate(() =>
        document.activeElement.classList.contains('jmdict-search-input'),
      ),
      `[${name}] lookup input focused`,
    )
    h.expectNone(
      await smallInputFonts(page),
      `[${name}] inputs at 16px or more`,
    )
    await page.fill('.jmdict-search-input', '犬')
    await page.locator('.drawer-backdrop').tap({ position: { x: 5, y: 200 } })
    await settle(page)
    await open(1)
    h.expect(
      (await page.inputValue('.jmdict-search-input')) === '犬',
      `[${name}] lookup keeps its query`,
    )
    await page.keyboard.press('Escape')
    await settle(page)

    h.step(`${name}: Tab order`)
    const landedInDrawer = []
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press('Tab')
      if (
        await page.evaluate(
          () => !!document.activeElement.closest('.sidebar, .right-panel'),
        )
      ) {
        landedInDrawer.push(i + 1)
      }
    }
    h.expect(
      landedInDrawer.length === 0,
      `[${name}] Tab skips closed drawers`,
      `landed in one on presses ${landedInDrawer}`,
    )
    await h.screenshot(page, 'new', { fullPage: false })
  }
})
