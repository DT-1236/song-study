// Step 4 of docs/completed/mobile.md: /settings, its link in the sidebar, the view
// settings shared with the document page, and the lyrics header's actions.
import {
  BASE,
  check,
  DESKTOP,
  PHONE,
  NARROW,
  sidewaysOverflow,
  tokenized,
} from '../harness.mjs'

await check('mobile-settings', async (h) => {
  const documentPath = `/documents/${h.seed.document_id}`
  const lyricsSize = (page) =>
    page.$eval('.lyrics-box', (el) => getComputedStyle(el).fontSize)

  h.step('desktop: link, shared value')
  const desk = await h.open('/documents', DESKTOP)
  await desk.click('.sidebar a[href="/settings"]')
  await desk.waitForSelector('#font-size')
  h.expect(
    await desk.$eval('.sidebar a[href="/settings"]', (a) =>
      a.classList.contains('active'),
    ),
    'the account link is active on /settings',
  )
  await desk.locator('#font-size').fill('24')
  await desk.goto(BASE + documentPath)
  await tokenized(desk)
  h.expect((await lyricsSize(desk)) === '24px', 'the document uses 24px')
  h.expect(
    (await desk.locator('#font-size').count()) === 1 &&
      (await desk.locator('#font-size').inputValue()) === '24',
    'the document grid shows the new value',
  )
  h.expect(
    (await desk.locator('.lyrics-header button').count()) >= 2,
    'Edit lyrics and Edit timings are in the lyrics header',
  )

  h.step('phone: link instead of grid')
  const phone = await h.open(documentPath, PHONE)
  await tokenized(phone)
  h.expect(
    (await phone.locator('.text-size-controls').count()) === 0,
    'no grid on the document page',
  )
  h.expect(
    (await phone
      .locator('a[href="/settings"]:has-text("View settings")')
      .count()) === 1,
    'a View settings link',
  )

  h.step('320px: /settings')
  const narrow = await h.open('/settings', NARROW)
  await narrow.waitForSelector('#font-size')
  h.expect((await sidewaysOverflow(narrow)).length === 0, 'no sideways scroll')
  await h.screenshot(narrow, 'settings', { fullPage: false })
})
