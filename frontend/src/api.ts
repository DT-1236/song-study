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

async function assertOk(
  response: Response,
  statusMessages: Record<number, string> = {},
): Promise<void> {
  if (response.ok) return

  if (response.status === 401) {
    // The session expired mid-use. A reload re-runs AuthGate's /auth/me
    // check, which lands on the login page; the thrown error covers the
    // moment before the reload takes effect.
    window.location.reload()
    throw new ApiError('Your session has expired. Please log in again.')
  }

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

export async function updateDocumentText(
  id: number,
  text: string,
): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// The forms of LRCLIB track reference linkLrclib and createDocument accept.
export const LRCLIB_URI_PLACEHOLDER =
  'e.g. https://lrclib.net/api/get/12345, or just 12345'

export async function linkLrclib(
  id: number,
  uri: string,
  replaceText: boolean,
): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/lrclib`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ uri, replace_text: replaceText }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

export async function unlinkLrclib(id: number): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/lrclib`, {
    method: 'DELETE',
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// Saves `lines` as the document's edited line timings, made for its lyrics
// as they were when editing started (`text`).
export async function saveLineTimings(
  id: number,
  text: string,
  lines: (LineTiming | null)[],
): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}/timings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, lines }),
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// How much of a song is in the user's head, as of the request: the mean
// chance of recalling each of its words, weighted by how often it's sung,
// with the words they have no card for yet at zero.
export type SongReadiness = {
  // 0 to 1.
  readiness: number
  // Words and grammar terms the song gives cards.
  words: number
  enrolled: number
  // Cards with a stability of 21 days or more.
  mature: number
  due: number
}

export type DocumentListItem = {
  id: number
  title: string
  youtube_video_id: string | null
  created_at: string
  readiness: SongReadiness
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
  // A word, rather than grammar.
  is_word: boolean
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
  // jmdict_miss: looked up in JMDict, with no entry found (senses empty).
  source: 'jmdict' | 'jmdict_miss' | 'english_stub' | 'composite'
  pieces: GlossPiece[]
  // The hiragana this was looked up as, for katakana with no dictionary
  // entry of its own (ココロノコエ as こころのこえ).
  looked_up_as: string | null
}

export type ConflictOptionValue = {
  reading: string
  furigana_spans: FuriganaSpan[]
  // The reading of the word's dictionary form, which its gloss is keyed by:
  // the same as `reading` unless the token is inflected. Missing from
  // options saved before it existed.
  citation_reading?: string
}

// A reading option from fetchAlternateReadings, which also says whether the
// token already offers it itself.
export type AlternateReadingOption = ConflictOptionValue & { own: boolean }

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

// Every reading tokenId can be given, one per reading: its own options (or
// the reading it was tokenized with), then every other reading JMDict has
// for its dictionary form, as reading options to apply with applyReading.
export async function fetchAlternateReadings(
  documentId: number,
  tokenId: number,
): Promise<AlternateReadingOption[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/${tokenId}/alternate-readings`,
  )

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
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/reading`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token_ids: tokenIds,
        reading,
        furigana_spans: furiganaSpans ?? null,
      }),
    },
  )

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

// Accepts phrase suggestions, or split predicate groups to merge again.
// Returns every token they changed.
export async function acceptPhraseSuggestions(
  documentId: number,
  conflictIds: number[],
): Promise<Token[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/accept-phrases`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conflict_ids: conflictIds }),
    },
  )

  await assertOk(response, { 404: 'Conflict option not found for this token.' })

  return response.json()
}

// Splits the group tokenId is merged into, found from any member of it.
// Returns every token it changed, or [] if tokenId isn't merged.
export async function unmergePhrase(
  documentId: number,
  tokenId: number,
): Promise<Token[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/${tokenId}/unmerge-phrase`,
    {
      method: 'POST',
    },
  )

  await assertOk(response, { 404: 'Token not found for this document.' })

  return response.json()
}

// Applies one of a phrase's alternative furigana splits (see
// PhraseFuriganaValue). Returns every affected token.
export async function resolvePhraseFurigana(
  documentId: number,
  conflictId: number,
): Promise<Token[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/phrase-furigana`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conflict_id: conflictId }),
    },
  )

  await assertOk(response, {
    404: 'Conflict option not found for this document.',
  })

  return response.json()
}

export async function setTokensIgnored(
  documentId: number,
  tokenIds: number[],
  ignored: boolean,
): Promise<Token[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/ignored`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token_ids: tokenIds, ignored }),
    },
  )

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

export type SortField =
  'id' | 'title' | 'youtube_video_id' | 'created_at' | 'readiness'
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

export async function searchJmdict(
  query: string,
  maxResultsPerTier = 3,
): Promise<JmdictEntry[]> {
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

export type CardKind = 'recognition' | 'grammar'

export type StudyCard = {
  id: number
  kind: CardKind
  lookup_form: string
  // Null for a grammar term.
  reading: string | null
  suspended: boolean
  due: string
  first_seen_document_id: number | null
}

export type CardAudio = {
  youtube_video_id: string
  // When the line is sung, in seconds into the video.
  start: number
  end: number
}

// The line of a song a card plays. Offsets are [begin, end) in Unicode code
// points, as the backend counts them, not in UTF-16 units.
export type CardLine = {
  document_id: number
  title: string
  index: number
  text: string
  token_id: number
  focus: [number, number]
  group: [number, number]
  // Null when the song has no video, or no timing for this line.
  audio: CardAudio | null
  // For a word or grammar term sung in katakana, its dictionary form as its
  // gloss writes it (声 for コエ); null for one that isn't.
  written_as: string | null
  // How the card's word can be corrected from here: by picking another
  // reading of the token, or for a word sung in katakana, another word with
  // its reading for `piece` of the token's gloss. Null for a grammar term or
  // an accepted phrase.
  correction: 'reading' | 'word' | null
  piece: number | null
}

export type CardOption = {
  // A word's option: the senses it shows, each as its glosses.
  senses: string[][] | null
  // A grammar term's option: what it says the term does.
  note: string | null
}

export type CardKanji = {
  character: string
  // Only the kun readings the word uses, with their okurigana in brackets.
  kun_readings: string[]
  more_kun: number
}

export type DeckWord = {
  card_id: number
  lookup_form: string
  reading: string | null
  status: 'new' | 'learning' | 'mature'
}

export type KanjiEntry = {
  on_readings: string[]
  meanings: string[]
  grade: number | null
  frequency: number | null
  radical: { character: string; meaning: string } | null
  components: string[]
  deck_words: DeckWord[]
}

export type QueuedCard = StudyCard & {
  // Null when the card's word is in none of the user's songs any more.
  line: CardLine | null
  options: CardOption[]
  // The index of the right option; null, with no options, for a word with
  // no dictionary entry to ask about any more.
  answer: number | null
  // A word's every sense, ranked, for the reveal.
  senses: GlossSense[]
  kanji: CardKanji[]
}

export type StudyQueue = {
  cards: QueuedCard[]
  // The sidebar entry of every kanji of the cards, by character.
  kanji: Record<string, KanjiEntry>
  // How many deck_words the sidebar lists under a kanji.
  max_deck_words: number
}

export type PushOutMonths = 1 | 3 | 6

// A word or grammar term of a song that the user's card for is fading.
export type WeakWord = {
  card_id: number
  lookup_form: string
  reading: string | null
  // Their chance of recalling it now, 0 to 1.
  retrievability: number
  // Where in its line it is, as [begin, end) offsets in code points.
  focus: [number, number]
  // Null for a word with no dictionary entry any more.
  meaning: CardOption | null
}

export type RunLine = {
  index: number
  text: string
  // Null when the song has no video, or no timing for this line.
  audio: CardAudio | null
  // Weakest first.
  weak: WeakWord[]
}

export type RunThrough = {
  youtube_video_id: string | null
  lines: RunLine[]
}

// The song's lines in order, with the words in each that the user is
// forgetting, for playing it through. Logs nothing and moves no card.
export async function fetchRunThrough(documentId: number): Promise<RunThrough> {
  const response = await fetch(`${API_URL}/documents/${documentId}/run-through`)

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

export async function fetchDocumentReadiness(
  documentId: number,
): Promise<SongReadiness> {
  const response = await fetch(`${API_URL}/documents/${documentId}/readiness`)

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

const CARD_ERRORS = {
  404: 'Card not found.',
  409: 'This card was removed from study.',
}

// Studies the song: enrolls its new words, up to its daily limit, and
// returns the due cards for its words.
export async function startSongSession(
  documentId: number,
): Promise<StudyQueue> {
  const response = await fetch(`${API_URL}/documents/${documentId}/study`, {
    method: 'POST',
  })

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

export async function fetchAllSongsQueue(): Promise<StudyQueue> {
  const response = await fetch(`${API_URL}/study/queue`)

  await assertOk(response)

  return response.json()
}

// `keepalive` lets the request finish after the page is gone.
export async function reviewCard(
  cardId: number,
  answer: { correct: boolean; durationMs: number; documentId: number | null },
  keepalive = false,
): Promise<{ rating: number; card: StudyCard }> {
  const response = await fetch(`${API_URL}/cards/${cardId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      correct: answer.correct,
      duration_ms: answer.durationMs,
      document_id: answer.documentId,
    }),
    keepalive,
  })

  await assertOk(response, CARD_ERRORS)

  return response.json()
}

export async function pushOutCard(
  cardId: number,
  months: PushOutMonths,
): Promise<StudyCard> {
  const response = await fetch(`${API_URL}/cards/${cardId}/push-out`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ months }),
  })

  await assertOk(response, CARD_ERRORS)

  return response.json()
}

export async function suspendCard(cardId: number): Promise<StudyCard> {
  const response = await fetch(`${API_URL}/cards/${cardId}/suspend`, {
    method: 'POST',
  })

  await assertOk(response, { 404: 'Card not found.' })

  return response.json()
}

// A word of a document the user can add to their cards, where it is.
export type DocumentWord = {
  // Every token of the word and what's glossed with it.
  token_ids: number[]
  // For a word or grammar term that's one piece of a gloss (a katakana
  // token's or a group's), which one.
  piece: number | null
  kind: CardKind
  lookup_form: string
  // Null for a grammar term.
  reading: string | null
  // How it can be corrected, as on a card (see CardLine).
  correction: 'reading' | 'word' | null
  // The user's card for it, removed or not; null if they have none.
  card: StudyCard | null
}

export async function fetchDocumentWords(
  documentId: number,
): Promise<DocumentWord[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/words`)

  await assertOk(response, { 404: 'Document not found.' })

  return response.json()
}

// Adds the word the token is part of to the user's cards, or restores it if
// they removed it. `piece` names which word or grammar term of the gloss's
// pieces, for a token sung in katakana or in a group.
export async function addTokenCard(
  documentId: number,
  tokenId: number,
  piece: number | null,
): Promise<StudyCard> {
  const url = new URL(
    `${API_URL}/documents/${documentId}/tokens/${tokenId}/card`,
    window.location.origin,
  )
  if (piece !== null) url.searchParams.set('piece', String(piece))
  const response = await fetch(url, { method: 'PUT' })

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

// A word a piece of katakana could be.
export type WordOption = {
  spelling: string
  // The glosses of its first sense.
  gloss: string[]
}

// Every word JMDict has with the reading of `piece` of the token's gloss,
// for a token sung in katakana.
export async function fetchPieceWords(
  documentId: number,
  tokenId: number,
  piece: number,
): Promise<WordOption[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/${tokenId}/pieces/${piece}/words`,
  )

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

// Makes `spelling` the word `piece` of each token's gloss is, for tokens
// sung in katakana. Returns the tokens.
export async function pickPieceWord(
  documentId: number,
  tokenIds: number[],
  piece: number,
  spelling: string,
): Promise<Token[]> {
  const response = await fetch(
    `${API_URL}/documents/${documentId}/tokens/piece-word`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token_ids: tokenIds, piece, spelling }),
    },
  )

  await assertOk(response, { 404: 'Token not found.' })

  return response.json()
}

// What correcting the word a card's line has did.
export type CardCorrection = {
  // The user's card for the word the line has now; null if it has no
  // dictionary entry to study.
  card: StudyCard | null
  // Whether the card corrected was kept, which it is once it has reviews.
  kept: boolean
}

// Picks another reading for the token a card's line has, moving the song to
// the card for the word that makes it. Logs no review.
export async function correctCardReading(
  cardId: number,
  correction: {
    documentId: number
    tokenId: number
    reading: string
    furiganaSpans: FuriganaSpan[]
  },
): Promise<CardCorrection> {
  const response = await fetch(`${API_URL}/cards/${cardId}/reading`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_id: correction.documentId,
      token_id: correction.tokenId,
      reading: correction.reading,
      furigana_spans: correction.furiganaSpans,
    }),
  })

  await assertOk(response, CARD_ERRORS)

  return response.json()
}

// Picks another word for `piece` of the katakana token a card's line has,
// moving the song to that word's card. Logs no review.
export async function correctCardWord(
  cardId: number,
  correction: {
    documentId: number
    tokenId: number
    piece: number
    spelling: string
  },
): Promise<CardCorrection> {
  const response = await fetch(`${API_URL}/cards/${cardId}/word`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_id: correction.documentId,
      token_id: correction.tokenId,
      piece: correction.piece,
      spelling: correction.spelling,
    }),
  })

  await assertOk(response, CARD_ERRORS)

  return response.json()
}
