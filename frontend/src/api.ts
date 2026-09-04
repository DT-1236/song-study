const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Document = {
  id: number
  title: string
  text: string
  youtube_video_id: string | null
  created_at: string
}

export class ApiError extends Error {}

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

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `Request failed (${response.status})`
    throw new ApiError(message)
  }

  return response.json()
}

export async function fetchDocument(id: number): Promise<Document> {
  const response = await fetch(`${API_URL}/documents/${id}`)

  if (!response.ok) {
    const message = response.status === 404 ? 'Document not found.' : `Request failed (${response.status})`
    throw new ApiError(message)
  }

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

export type SortField = 'id' | 'title' | 'youtube_video_id' | 'created_at'
export type SortDir = 'asc' | 'desc'

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

  if (!response.ok) {
    throw new ApiError(`Request failed (${response.status})`)
  }

  return response.json()
}
