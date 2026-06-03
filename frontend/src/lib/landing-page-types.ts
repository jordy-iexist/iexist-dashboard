export type LandingPageRowData = {
  website?: string
  onderwerp?: string
  lengte?: string
  primaire_zoekwoorden?: string
  secundaire_zoekwoorden?: string
}

export type LandingPageListItem = {
  id: string
  meta_title: string | null
  onderwerp: string
  filename: string
  status: string
  created_at: string
}

export type LandingPageListResponse = {
  landing_pages: LandingPageListItem[]
  total: number
  page: number
  page_size: number
}

export type LandingPageDetailPayload = {
  id: string
  content: string
  meta_title: string | null
  meta_description: string | null
  slug: string | null
  share_token: string
  status: string
  onderwerp: string
  filename: string
  created_at: string
}

export type LandingPageUploadResponse = {
  upload_id: string
  rows_count: number
  jobs_queued: number
  skipped_rows: number
  status: string
}

export type LandingPageRecentUploadItem = {
  upload_id: string
  filename: string
  created_at: string
  total_jobs: number
  completed: number
  failed: number
  canceled: number
  processed: number
  is_done: boolean
  final_status: "processing" | "completed" | "completed_with_errors" | "canceled"
}

export type LandingPageRecentUploadsResponse = {
  uploads: LandingPageRecentUploadItem[]
}

export type LandingPageUploadStatus = {
  upload_id: string
  filename: string
  total_jobs: number
  completed: number
  failed: number
  processing: number
  pending: number
  canceled: number
  processed: number
  remaining: number
  skipped_rows: number
  is_done: boolean
  final_status: "processing" | "completed" | "completed_with_errors" | "canceled"
}

export type LandingPageGenerationSettings = {
  system_prompt: string | null
  reasoning_effort: string | null
  model: string | null
  max_output_tokens: number | null
  effective_system_prompt: string
  effective_reasoning_effort: string
  effective_model: string
  effective_max_output_tokens: number
}
