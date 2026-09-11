const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Document = {
  id: number
  title: string
  text: string
  youtube_video_id: string | null
  created_at: string
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
}): Promise<Document> {
  const response = await fetch(`${API_URL}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: input.title,
      text: input.text,
      youtube_video_id: input.youtubeVideoId || null,
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

export async function resolveConflict(
  documentId: number,
  tokenId: number,
  conflictId: number,
): Promise<Token> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/${tokenId}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conflict_id: conflictId }),
  })

  await assertOk(response, { 404: 'Conflict option not found.' })

  return response.json()
}

export async function correctReading(documentId: number, tokenId: number, reading: string): Promise<Token> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens/${tokenId}/correct`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reading }),
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
