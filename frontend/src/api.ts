// The API is served under /api on the app's own origin (the Vite dev server
// proxies it; a deployment's reverse proxy does the same).
const API_URL = '/api'

export type LineTiming = {
  start: number
  end: number
}

export type Document = {
  id: number
  title: string
  text: string
  youtube_video_id: string | null
  lrclib_uri: string | null
  // Whether LRCLIB's lyrics replace the document's own, rather than the
  // document keeping them; null while it isn't linked.
  lrclib_replaces_text: boolean | null
  // When each line of `text` is sung, in seconds into the track, from
  // LRCLIB's synced lyrics; null without them.
  lrclib_lines: LineTiming[] | null
  // The line timings as edited on this page, used in place of
  // lrclib_lines: one per line, null for a line whose timing was deleted.
  // Null without edits, or once the text isn't what they were made for.
  edited_lines: (LineTiming | null)[] | null
  created_at: string
  // Set when a linked document's lyrics couldn't be refreshed from LRCLIB
  // on this load, in which case the stored ones were returned.
  lrclib_sync_error: string | null
}

export class ApiError extends Error {}

export type CurrentUser = {
  id: number
  name: string
  email: string | null
}

// Where the browser goes to log in with Google; it comes back to the app.
export const LOGIN_URL = `${API_URL}/auth/login`

// The logged-in user, or null if nobody is.
export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const response = await fetch(`${API_URL}/auth/me`)
  if (response.status === 401) return null
  await assertOk(response)
  return response.json()
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_URL}/auth/logout`, { method: 'POST' })
  await assertOk(response)
}

// The message to show for a failed request: the server's own, from an
// ApiError, or `fallback` for anything else (a network failure, say).
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

async function assertOk(response: Response, statusMessages: Record<number, string> = {}): Promise<void> {
  if (response.ok) return

  if (statusMessages[response.status]) {
    throw new ApiError(statusMessages[response.status])
  }

  const body = await response.json().catch(() => null)
  if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === 'string') {
    // FastAPI/pydantic validation error shape: {"detail": [{"msg": "Value error, ...", ...}]}
    throw new ApiError(body.detail[0].msg.replace(/^Value error,\s*/, ''))
  }
  if (typeof body?.detail === 'string') {
    throw new ApiError(body.detail)
  }
  throw new ApiError(`Request failed (${response.status})`)
}

export async function createDocument(input: {
  title: string
  text: string
  youtubeVideoId: string
  lrclibUri: string
}): Promise<Document> {
  const response = await fetch(`${API_URL}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: input.title,
      text: input.text,
      youtube_video_id: input.youtubeVideoId || null,
      lrclib_uri: input.lrclibUri || null,
    }),
  })

  await assertOk(response)

  return response.json()
}

export async function fetchDocument(id: number): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}`)

  await assertOk(response)

  return response.json()
}

export async function updateDocumentText(id: number, text: string): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// The forms of LRCLIB track reference linkLrclib and createDocument accept.
export const LRCLIB_URI_PLACEHOLDER = 'e.g. https://lrclib.net/api/get/12345, or just 12345'

export async function linkLrclib(id: number, uri: string, replaceText: boolean): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/lrclib`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uri, replace_text: replaceText }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

export async function unlinkLrclib(id: number): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/lrclib`, { method: 'DELETE' })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// Saves `lines` as the document's edited line timings, made for its lyrics
// as they were when editing started (`text`).
export async function saveLineTimings(id: number, text: string, lines: (LineTiming | null)[]): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/timings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, lines }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

export type DocumentListItem = {
  id: number
  title: string
  youtube_video_id: string | null
  created_at: string
}

export type DocumentPage = {
  items: DocumentListItem[]
  total: number
  page: number
  page_size: number
}

export type FuriganaSpan = {
  start: number
  end: number
  text: string
  reading: string | null
}

export type GlossSense = {
  entry_idseq: number
  pos: string[]
  misc: string[]
  field: string[]
  gloss: string[]
}

export type GlossPiece = {
  surface: string
  reading: string
  senses: GlossSense[]
  ambiguous_readings: string[]
  // What a grammar word or helper verb adds to the word before it, for a
  // piece of a group's gloss (see backend/app/grammar.py).
  note: string | null
}

export type Gloss = {
  reading: string
  // What this was looked up under — usually the token's own
  // dictionary_form, but for a merged group (see phrase_start_position) the
  // phrase's headword (この期に及んで) or the group's parts
  // (欲する＋てる＋ん＋だ＋って).
  lookup_form: string
  senses: GlossSense[]
  source: 'jmdict' | 'english_stub' | 'composite'
  pieces: GlossPiece[]
  // The hiragana this was looked up as, for katakana with no dictionary
  // entry of its own (ココロノコエ as こころのこえ).
  looked_up_as: string | null
}

export type ConflictOptionValue = {
  reading: string
  furigana_spans: FuriganaSpan[]
}

// A suggested multi-token JMDict headword starting at this token (see
// backend/app/phrase_merge.py): the headword and its reading, the on-page
// text it covers with any grammar attached after it (真に受け + てみて),
// and how many tokens that is, this one included.
export type PhraseConflictValue = {
  surface: string
  lookup_form: string
  reading: string
  token_count: number
  // How many of those tokens the headword itself covers.
  phrase_token_count?: number
}

// A predicate group starting at this token (see backend/app/grammar.py),
// which merges it again after it's been split.
export type PredicateGroupValue = {
  surface: string
  token_count: number
}

// An alternative furigana split for an accepted phrase: an update per token
// it changes, `offset` tokens after the phrase's first token.
export type PhraseFuriganaValue = {
  updates: { offset: number; furigana_spans: FuriganaSpan[] }[]
}

export type Conflict =
  | {
      id: number
      kind: 'heteronym' | 'no_kana_anchor' | 'custom'
      value: ConflictOptionValue
      selected: boolean
    }
  | {
      id: number
      kind: 'phrase'
      value: PhraseConflictValue
      selected: boolean
    }
  | {
      id: number
      kind: 'phrase_furigana'
      value: PhraseFuriganaValue
      selected: boolean
    }
  | {
      id: number
      kind: 'predicate'
      value: PredicateGroupValue
      selected: boolean
    }

export type Token = {
  id: number
  document_id: number
  position: number
  char_begin: number
  char_end: number
  surface: string
  dictionary_form: string
  dictionary_form_reading: string
  dictionary_form_note: string | null
  normalized_form: string
  reading_katakana: string
  part_of_speech: string[]
  is_oov: boolean
  furigana_spans: FuriganaSpan[]
  needs_review: boolean
  review_reason: string | null
  furigana_override: FuriganaSpan[] | null
  // Marked by the user as needing no gloss, like a name no dictionary has.
  gloss_ignored: boolean
  is_english: boolean
  gloss: Gloss | null
  conflicts: Conflict[]
  start_time: string | null
  end_time: string | null
  // The first token's position when this token is merged with its
  // neighbors into one group, the same across the group; else null. See
  // acceptPhraseSuggestions/unmergePhrase.
  phrase_start_position: number | null
  // What that group is: an accepted phrase suggestion, or a predicate with
  // its grammar, grouped automatically.
  group_kind: 'phrase' | 'predicate' | null
}

export async function fetchTokens(documentId: number): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens`)

  await assertOk(response)

  return response.json()
}

// Every other reading JMDict has for tokenId's dictionary form, as reading
// options to apply with applyReading.
export async function fetchAlternateReadings(documentId: number, tokenId: number): Promise<ConflictOptionValue[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/${tokenId}/alternate-readings`)

  await assertOk(response, { 404: 'Token not found for this document.' })

  return response.json()
}

// Selects `reading` for each of the tokens: the option each has with that
// reading (preferring `furiganaSpans` as its split), or else a correction.
// Returns every token whose gloss changed, which includes the rest of any
// group one of them is in.
export async function applyReading(
  documentId: number,
  tokenIds: number[],
  reading: string,
  furiganaSpans?: FuriganaSpan[],
): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/reading`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token_ids: tokenIds, reading, furigana_spans: furiganaSpans ?? null }),
  })

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

// Accepts phrase suggestions, or split predicate groups to merge again.
// Returns every token they changed.
export async function acceptPhraseSuggestions(documentId: number, conflictIds: number[]): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/accept-phrases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conflict_ids: conflictIds }),
  })

  await assertOk(response, { 404: 'Conflict option not found for this token.' })

  return response.json()
}

// Splits the group tokenId is merged into, found from any member of it.
// Returns every token it changed, or [] if tokenId isn't merged.
export async function unmergePhrase(documentId: number, tokenId: number): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/${tokenId}/unmerge-phrase`, {
    method: 'POST',
  })

  await assertOk(response, { 404: 'Token not found for this document.' })

  return response.json()
}

// Applies one of a phrase's alternative furigana splits (see
// PhraseFuriganaValue). Returns every affected token.
export async function resolvePhraseFurigana(documentId: number, conflictId: number): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/phrase-furigana`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conflict_id: conflictId }),
  })

  await assertOk(response, { 404: 'Conflict option not found for this document.' })

  return response.json()
}

export async function setTokensIgnored(documentId: number, tokenIds: number[], ignored: boolean): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/ignored`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token_ids: tokenIds, ignored }),
  })

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

export type SortField = 'id' | 'title' | 'youtube_video_id' | 'created_at'
export type SortDir = 'asc' | 'desc'

export type JmdictSense = {
  pos: string[]
  misc: string[]
  field: string[]
  gloss: string[]
}

export type JmdictEntry = {
  idseq: number
  kanji_forms: string[]
  kana_forms: string[]
  senses: JmdictSense[]
}

export async function searchJmdict(query: string, maxResultsPerTier = 3): Promise<JmdictEntry[]> {
  const url = new URL(`${API_URL}/jmdict/search`, window.location.origin)
  url.searchParams.set('q', query)
  url.searchParams.set('max_results_per_tier', String(maxResultsPerTier))

  const response = await fetch(url)

  await assertOk(response)

  return response.json()
}

export async function fetchDocuments(params: {
  page: number
  pageSize: number
  sortBy: SortField
  sortDir: SortDir
}): Promise<DocumentPage> {
  const url = new URL(`${API_URL}/documents`, window.location.origin)
  url.searchParams.set('page', String(params.page))
  url.searchParams.set('page_size', String(params.pageSize))
  url.searchParams.set('sort_by', params.sortBy)
  url.searchParams.set('sort_dir', params.sortDir)

  const response = await fetch(url)

  await assertOk(response)

  return response.json()
}
