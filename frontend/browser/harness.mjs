// Shared setup and measurements for headless browser checks of the app,
// run against the harness's test-database servers (`make browser-up`).
// docs/browser-checks.md says how to write and run a check.
import { chromium, devices } from 'playwright-core'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const STATE = join(REPO, '.browser-harness')
// Big Buck Bunny, from the Blender Foundation (CC BY 3.0): any embeddable
// video does, since checks only read its playback time.
const VIDEO_ID = 'aqz-KE-bpKQ'

export const BASE = `http://localhost:${process.env.BROWSER_WEB_PORT ?? 5199}`
const BRAVE =
  process.env.BRAVE_PATH ??
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
// tests.support's TEST_USER_ID, which the harness backend acts as.
const TEST_USER_ID = 1000

// Short enough that a wrong selector fails while there's still time to read
// why: Playwright's own 30s default, a few times over, outlasts the shell
// command running the check.
const ACTION_TIMEOUT = 5_000
const NAVIGATION_TIMEOUT = 15_000
// Under the 120s a shell command gets by default, so the check reports and
// exits rather than being cut off mid-run.
const CHECK_TIMEOUT = Number(process.env.BROWSER_CHECK_TIMEOUT ?? 100) * 1000

// What a page may load besides the app: the YouTube player and what it pulls in.
const ALLOWED_HOSTS =
  /(^|\.)(youtube\.com|youtube-nocookie\.com|ytimg\.com|googlevideo\.com|ggpht\.com|google\.com|gstatic\.com|googleapis\.com|doubleclick\.net)$/

// The device contexts every layout check runs in (docs/mobile.md, "The phone
// harness"). Phone sizes are emulated in Chromium, not WebKit, so iOS-only
// behavior still needs a real phone.
const { defaultBrowserType: _, ...iPhone13 } = devices['iPhone 13']
export const PHONE = { name: 'phone', options: iPhone13 }
export const NARROW = {
  name: 'narrow',
  options: {
    viewport: { width: 320, height: 640 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 2,
  },
}
export const LANDSCAPE = {
  name: 'landscape',
  options: {
    viewport: { width: 932, height: 430 },
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 3,
  },
}
export const DESKTOP = {
  name: 'desktop',
  options: { viewport: { width: 1280, height: 800 } },
}
export const PHONES = [PHONE, NARROW]
export const ALL_DEVICES = [PHONE, NARROW, LANDSCAPE, DESKTOP]

function die(message) {
  console.error(`browser check not run: ${message}`)
  process.exit(2)
}

function firstLine(error) {
  return String(error?.message ?? error).split('\n')[0]
}

// Refuses to start unless Brave is installed and the harness backend is the
// one answering, so a check can't run against the app database or burn its
// time budget waiting on servers that aren't there.
async function preflight() {
  if (!existsSync(BRAVE)) die(`no browser at ${BRAVE}; set BRAVE_PATH`)
  let me
  try {
    const response = await fetch(`${BASE}/api/auth/me`, {
      signal: AbortSignal.timeout(3_000),
    })
    me = await response.json()
  } catch {
    die(`nothing answering at ${BASE}; start the servers with make browser-up`)
  }
  if (me?.id !== TEST_USER_ID) {
    die(
      `${BASE} doesn't answer as the harness's test user ${TEST_USER_ID} ` +
        `(got ${JSON.stringify(me)}); it may be the app's own backend, so ` +
        `nothing was run`,
    )
  }
  try {
    return JSON.parse(readFileSync(join(STATE, 'seed.json'), 'utf8'))
  } catch {
    die('no .browser-harness/seed.json; restart with make browser-up FRESH=1')
  }
}

class Harness {
  constructor(name, seed) {
    this.name = name
    // `document_id`: a tokenized public-domain text (tests/fixtures/kumo_no_ito.py).
    this.seed = seed
    this.outDir =
      process.env.BROWSER_OUT_DIR ??
      join(STATE, 'out', name.replace(/[^\w-]+/g, '-'))
    mkdirSync(this.outDir, { recursive: true })
    this.passed = 0
    this.failed = []
    this.notes = new Set()
    this.pages = []
    this.currentStep = 'starting'
  }

  // Labels what the check does next, so a failure or timeout says where.
  step(label) {
    this.currentStep = label
    console.log(`· ${label}`)
  }

  expect(condition, message, detail) {
    if (condition) {
      this.passed++
      console.log(`  PASS ${message}`)
    } else {
      this.fail(detail === undefined ? message : `${message}: ${detail}`)
    }
  }

  // Passes when `found` (a measurement's list of offenders) is empty, and
  // otherwise names the first few.
  expectNone(found, message) {
    const shown = found.slice(0, 5).join('; ')
    const more = found.length > 5 ? ` (+${found.length - 5} more)` : ''
    this.expect(found.length === 0, message, `${shown}${more}`)
  }

  fail(message) {
    this.failed.push(message)
    console.log(`  FAIL ${message}`)
  }

  // A page at `path` in a new context emulating `device`, ready once the app
  // has rendered. Pages are closed with the browser at the end of the check.
  async open(path, device = DESKTOP) {
    const context = await this.browser.newContext({
      ...device.options,
      baseURL: BASE,
    })
    context.setDefaultTimeout(ACTION_TIMEOUT)
    context.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT)
    // Backstop for the app database: nothing leaves the harness's origin
    // except to YouTube.
    await context.route('**/*', (route) => {
      const url = new URL(route.request().url())
      if (url.origin === BASE || ALLOWED_HOSTS.test(url.hostname)) {
        return route.continue()
      }
      if (url.protocol === 'data:' || url.protocol === 'blob:') {
        return route.continue()
      }
      this.notes.add(`blocked request to ${url.origin}`)
      return route.abort()
    })
    const page = await context.newPage()
    page.device = device
    page.on('pageerror', (error) =>
      this.fail(`[${device.name}] uncaught page error: ${firstLine(error)}`),
    )
    page.on('console', async (message) => {
      if (message.type() !== 'error') return
      // React's warnings are format strings ("%s cannot appear as a
      // descendant of <%s>") with the values as further arguments, and end
      // in a component stack too long to read in a report.
      const [format, ...values] = await Promise.all(
        message.args().map((arg) => arg.jsonValue().catch(() => '?')),
      ).catch(() => [message.text()])
      const text =
        typeof format === 'string'
          ? format.replace(/%s/g, () => String(values.shift() ?? ''))
          : message.text()
      this.notes.add(
        `[${device.name}] console error: ${text.trim().split('\n')[0].slice(0, 200)}`,
      )
    })
    page.on('response', (response) => {
      if (response.url().startsWith(BASE) && response.status() >= 500) {
        this.fail(
          `[${device.name}] ${response.status()} from ${response.request().method()} ${response.url().slice(BASE.length)}`,
        )
      }
    })
    this.pages.push(page)
    await page.goto(path)
    await page.waitForSelector('#root > *')
    return page
  }

  // Saves a screenshot to the check's output folder and returns its path;
  // Read the PNG to look at it.
  async screenshot(page, label, options = {}) {
    const path = join(this.outDir, `${page.device.name}-${label}.png`)
    await page.screenshot({ path, fullPage: true, ...options })
    console.log(`  shot ${path}`)
    return path
  }

  // Calls the harness backend's API as the test user, for setup a check
  // needs beyond the seed. Throws on a non-2xx status.
  async api(method, path, body) {
    const response = await fetch(`${BASE}/api${path}`, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(NAVIGATION_TIMEOUT),
    })
    const text = await response.text()
    if (!response.ok) {
      throw new Error(`${method} ${path}: ${response.status} ${text}`)
    }
    return text ? JSON.parse(text) : null
  }

  // The id of a document of the seeded text with a YouTube video, made on
  // first use and found again after that: the seed has no video, and a video
  // ID can belong to only one document.
  async videoDocument() {
    const { items } = await this.api('GET', '/documents?page=1&page_size=100')
    const found = items.find((doc) => doc.youtube_video_id === VIDEO_ID)
    if (found) return found.id
    const seeded = await this.api('GET', `/documents/${this.seed.document_id}`)
    const created = await this.api('POST', '/documents', {
      title: `${seeded.title} (video)`,
      text: seeded.text,
      youtube_video_id: VIDEO_ID,
    })
    return created.id
  }

  async screenshotPagesAfterFailure() {
    for (const page of this.pages) {
      if (page.isClosed()) continue
      const path = join(this.outDir, `${page.device.name}-at-failure.png`)
      await page
        .screenshot({ path, timeout: 3_000 })
        .then(() => console.log(`  shot ${path}`))
        .catch(() => {})
    }
  }

  report() {
    for (const note of this.notes) console.log(`  note ${note}`)
    const total = this.passed + this.failed.length
    console.log(
      this.failed.length
        ? `${this.name}: ${this.failed.length} of ${total} FAILED`
        : `${this.name}: all ${total} passed`,
    )
    console.log(`output: ${this.outDir}`)
  }
}

// Runs `body(h)` against a fresh headless Brave, prints a PASS/FAIL line per
// expectation and a summary, and exits non-zero if anything failed. A check
// still running after BROWSER_CHECK_TIMEOUT seconds (default 100) is stopped
// and reported as failed at the step it was on.
export async function check(name, body) {
  const seed = await preflight()
  const h = new Harness(name, seed)
  const watchdog = setTimeout(async () => {
    h.fail(
      `still running after ${CHECK_TIMEOUT / 1000}s, at "${h.currentStep}"`,
    )
    await Promise.race([
      h.screenshotPagesAfterFailure(),
      new Promise((done) => setTimeout(done, 5_000)),
    ])
    h.report()
    // Playwright kills the browser it launched as the process exits.
    process.exit(1)
  }, CHECK_TIMEOUT)
  try {
    h.browser = await chromium.launch({
      executablePath: BRAVE,
      args: ['--autoplay-policy=no-user-gesture-required'],
    })
    await body(h)
  } catch (error) {
    h.fail(`threw at "${h.currentStep}": ${firstLine(error)}`)
    await h.screenshotPagesAfterFailure()
  } finally {
    clearTimeout(watchdog)
    await h.browser?.close().catch(() => {})
  }
  h.report()
  process.exit(h.failed.length ? 1 : 0)
}

// --- Measurements. Each takes a page and returns what a check asserts on. ---

// Resolves once no CSS transition or animation is running, such as a drawer
// sliding, so a measurement reads where things end up rather than a guessed
// `waitForTimeout`. Infinite animations (a spinner) are ignored.
export async function settle(page) {
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (animation) =>
          animation.playState !== 'running' ||
          animation.effect?.getTiming().iterations === Infinity,
      ),
  )
}

// Whether `selector` matches an element that's rendered with a size and at
// least partly inside the viewport.
export function isShown(page, selector) {
  return page.evaluate((selector) => {
    const element = document.querySelector(selector)
    if (!element) return false
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return (
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      rect.width > 0 &&
      rect.height > 0 &&
      rect.right > 0 &&
      rect.left < innerWidth &&
      rect.bottom > 0 &&
      rect.top < innerHeight
    )
  }, selector)
}

// The elements reaching past the viewport's right edge, empty when the page
// doesn't scroll sideways.
export function sidewaysOverflow(page) {
  return page.evaluate(() => {
    if (document.documentElement.scrollWidth <= innerWidth) return []
    return [...document.querySelectorAll('body *')]
      .filter((element) => element.getBoundingClientRect().right > innerWidth)
      .map(
        (element) =>
          `${element.tagName.toLowerCase()}${element.className ? '.' + String(element.className).trim().replace(/\s+/g, '.') : ''} right=${Math.round(element.getBoundingClientRect().right)}`,
      )
  })
}

// The visible buttons, links, inputs and summaries inside `scope` whose hit
// area is under 44×44 CSS px. A hit area counts what `elementFromPoint`
// resolves to the target, so a padded pseudo-element counts toward it.
export function smallTapTargets(page, scope = 'body') {
  return page.evaluate((scope) => {
    const MIN = 44
    const hits = (target, x, y) => {
      const found = document.elementFromPoint(x, y)
      return found !== null && (found === target || target.contains(found))
    }
    const small = []
    for (const target of document
      .querySelector(scope)
      .querySelectorAll('button, a[href], input, summary, select')) {
      const rect = target.getBoundingClientRect()
      const style = getComputedStyle(target)
      if (
        rect.width === 0 ||
        style.visibility === 'hidden' ||
        rect.bottom < 0 ||
        rect.top > innerHeight
      ) {
        continue
      }
      if (rect.width >= MIN && rect.height >= MIN) continue
      const cx = rect.left + rect.width / 2
      const cy = rect.top + rect.height / 2
      const half = MIN / 2 - 1
      const wide = hits(target, cx - half, cy) && hits(target, cx + half, cy)
      const tall = hits(target, cx, cy - half) && hits(target, cx, cy + half)
      if (wide && tall) continue
      const label = (
        target.getAttribute('aria-label') ??
        target.textContent ??
        ''
      )
        .trim()
        .slice(0, 30)
      small.push(
        `${target.tagName.toLowerCase()} "${label}" ${Math.round(rect.width)}×${Math.round(rect.height)}`,
      )
    }
    return small
  }, scope)
}

// The visible text inputs, textareas and selects with a computed font size
// under 16px, which iOS Safari zooms in on when focused.
export function smallInputFonts(page) {
  return page.evaluate(() =>
    [
      ...document.querySelectorAll(
        'input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]), textarea, select',
      ),
    ]
      .filter((element) => element.getBoundingClientRect().width > 0)
      .map((element) => [
        element,
        parseFloat(getComputedStyle(element).fontSize),
      ])
      .filter(([, size]) => size < 16)
      .map(
        ([element, size]) =>
          `${element.tagName.toLowerCase()}${element.className ? '.' + element.className.trim().split(/\s+/)[0] : ''} ${size}px`,
      ),
  )
}

// A locator for the `nth` token reading `surface`. A token's text includes
// its furigana (and an open gloss popup), so matching on Playwright's
// `hasText` alone would miss it.
export async function token(page, surface, nth = 0) {
  const index = await page.evaluate(
    ([surface, nth]) =>
      [...document.querySelectorAll('.token')]
        .map((element) => {
          const copy = element.cloneNode(true)
          copy.querySelectorAll('rt, .gloss-popup').forEach((n) => n.remove())
          return copy.textContent
        })
        .reduce(
          (found, text, i) => (text === surface ? [...found, i] : found),
          [],
        )[nth] ?? -1,
    [surface, nth],
  )
  if (index === -1) throw new Error(`no token #${nth} reading ${surface}`)
  return page.locator('.token').nth(index)
}

// The YouTube player's frame, once its <video> exists: the player isn't
// ready for several seconds after the page loads.
export async function videoFrame(page, timeout = 20_000) {
  const iframe = await page.waitForSelector('iframe[src*="youtube"]', {
    timeout,
  })
  const frame = await iframe.contentFrame()
  await frame.waitForSelector('video', { state: 'attached', timeout })
  return frame
}

// The video's playback position in seconds.
export async function videoTime(page) {
  const frame = await videoFrame(page)
  return frame.evaluate(() => document.querySelector('video').currentTime)
}

// Taps `locator` on a touch device and clicks it otherwise: `tap()` throws
// in a context without touch, such as DESKTOP.
export function tapOrClick(page, locator) {
  return page.device.options.hasTouch ? locator.tap() : locator.click()
}

// Swaps the viewport's width and height, keeping the page, as turning a
// phone does.
export async function rotate(page) {
  const { width, height } = page.viewportSize()
  await page.setViewportSize({ width: height, height: width })
}
