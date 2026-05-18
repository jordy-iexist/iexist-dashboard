export type WordPressSite = {
  id: string
  name: string
  base_url: string
  wp_login: string
  is_active: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export type PublicationStatus =
  | "pending"
  | "processing"
  | "succeeded"
  | "failed"
  | "blocked_duplicate"

export type PublicationItem = {
  id: string
  blog_id: string
  wordpress_site_id: string
  status: PublicationStatus
  requested_by: string
  wp_post_id: string | null
  wp_post_url: string | null
  wp_media_id: string | null
  blog_image_id: string | null
  wp_status: "draft" | "publish"
  error_code: string | null
  error_message: string | null
  warning_code: string | null
  warning_message: string | null
  created_at: string
  updated_at: string
}

export type BlockedPublicationItem = {
  blog_id: string
  wordpress_site_id: string
  status: "blocked_duplicate"
  reason: string
}

export type PublishActionResponse = {
  requested: number
  queued: number
  blocked_duplicates: number
  publications: PublicationItem[]
  blocked: BlockedPublicationItem[]
}

export type BlogImageSource = "auto_generated" | "manual_upload"

export type BlogImage = {
  id: string
  blog_id: string
  source: BlogImageSource
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

export type BlogImageGenerationState =
  | "idle"
  | "pending"
  | "processing"
  | "completed"
  | "failed"

export type BlogImageGenerationStatus = {
  blog_id: string
  state: BlogImageGenerationState
  progress_percent: number
  message: string
  job_id: string | null
  error_message: string | null
  has_primary_image: boolean
  primary_image_id: string | null
  primary_image_created_at: string | null
}
