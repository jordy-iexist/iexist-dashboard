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
  share_token: string
  is_public?: boolean
  is_owner?: boolean
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
  share_token: string
  is_public?: boolean
  is_owner?: boolean
}

export type BlogSharePayload = {
  id: string
  content: string
  created_at: string
  images: BlogImageItem[]
}

export type BlogImageItem = {
  id: string
  blog_id: string
  source: "auto_generated" | "manual_upload"
  storage_path: string
  signed_url: string | null
  mime_type: string
  file_size_bytes: number
  width: number | null
  height: number | null
  is_primary: boolean
  generation_prompt: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type BlogDetailResponse = BlogDetailPayload
