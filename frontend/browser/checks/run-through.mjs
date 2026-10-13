// The run-through page's Start, pressed before the player is ready: the
// song starts from its first line once the player has loaded.
import { check, DESKTOP, videoFrame } from '../harness.mjs'

await check('run-through', async (h) => {
  const id = await h.videoDocument()
  const { text } = await h.api('GET', `/documents/${id}`)
  // Each lyric line five seconds long, from 30 s in.
  const lines = text
    .split('\n')
    .map((line, i) =>
      line.trim() ? { start: 30 + i * 5, end: 35 + i * 5 } : null,
    )
  await h.api('PUT', `/documents/${id}/timings`, { text, lines })
  const first = lines.find(Boolean)

  h.step('Start before the player is ready')
  const page = await h.open(`/documents/${id}/run-through`, DESKTOP)
  const start = page.getByRole('button', { name: /Start/ })
  await start.click()
  h.expect(
    await start.isHidden(),
    'Start is enabled at once, and starting hides it',
  )

  const frame = await videoFrame(page)
  await frame.waitForFunction(
    (from) => document.querySelector('video').currentTime > from,
    first.start,
    { timeout: 20_000, polling: 250 },
  )
  h.expect(true, `the video plays from the first line, past ${first.start}s`)
})
