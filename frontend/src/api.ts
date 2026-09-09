const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Document = {
  id: number
  title: string
  text: string
  youtube_video_id: string | null
  created_at: string
}

export class ApiError extends Error {}

async function assertOk(response: Response): Promise<void> {
  if (response.ok) return

  const body = await response.json().catch(() => null)
  const message =
    typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status})`
  throw new ApiError(message)
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

export type Token = {
  id: number
  document_id: number
  position: number
  char_begin: number
  char_end: number
  surface: string
  dictionary_form: string
  normalized_form: string
  reading_katakana: string
  part_of_speech: string[]
  is_oov: boolean
  furigana_spans: FuriganaSpan[]
  needs_review: boolean
  review_reason: string | null
  furigana_override: FuriganaSpan[] | null
  start_time: string | null
  end_time: string | null
}

export async function fetchTokens(documentId: number): Promise<Token[]> {
  const response = await fetch(`${API_URL}/documents/${documentId}/tokens`)

  await assertOk(response)

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

export async function searchJmdict(query: string): Promise<JmdictEntry[]> {
  const url = new URL(`${API_URL}/jmdict/search`)
  url.searchParams.set('q', query)

  const response = await fetch(url)

  if (!response.ok) {
    throw new ApiError(`Request failed (${response.status})`)
  }

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
