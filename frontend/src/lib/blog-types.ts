export type BlogPublicationSummary = {
  total: number
  succeeded: number
  failed: number
  pending: number
  processing: number
}

export type BlogRowData = {
  klant?: string
  woorden?: string
  anker_1?: string
  anker_1_url?: string
  anker_2?: string
  anker_2_url?: string
}

export type BlogListItemPayload = {
  id: string
  row_data: BlogRowData | null
  content: string
  created_at: string
  filename: string
  published_at?: string | null
  publication?: BlogPublicationSummary | null
}

export type BlogsListResponse = {
  blogs: BlogListItemPayload[]
  total: number
  page: number
  page_size: number
}

export type BlogDetailPayload = {
  id: string
  content: string
  created_at: string
  filename: string
  status: string
  published_at?: string | null
  row_data: BlogRowData | null
}

export type BlogDetailResponse = BlogDetailPayload
