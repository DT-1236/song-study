const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

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
  created_at: string
  // Set when a linked document's lyrics couldn't be refreshed from LRCLIB
  // on this load, in which case the stored ones were returned.
  lrclib_sync_error: string | null
}

export class ApiError extends Error {}

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
}

export type Gloss = {
  reading: string
  senses: GlossSense[]
  source: 'jmdict' | 'english_stub' | 'composite'
  pieces: GlossPiece[]
}

export type ConflictOptionValue = {
  reading: string
  furigana_spans: FuriganaSpan[]
}

export type Conflict = {
  id: number
  kind: 'heteronym' | 'no_kana_anchor' | 'custom'
  value: ConflictOptionValue
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
}

export async function fetchTokens(documentId: number): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens`)

  await assertOk(response)

  return response.json()
}

// Selects `reading` for each of the tokens: the option each has with that
// reading (preferring `furiganaSpans` as its split), or else a correction.
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
  const url = new URL(`${API_URL}/jmdict/search`)
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
  const url = new URL(`${API_URL}/documents`)
  url.searchParams.set('page', String(params.page))
  url.searchParams.set('page_size', String(params.pageSize))
  url.searchParams.set('sort_by', params.sortBy)
  url.searchParams.set('sort_dir', params.sortDir)

  const response = await fetch(url)

  await assertOk(response)

  return response.json()
}
