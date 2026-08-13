export type CustomerWebsite = {
  id: string
  name: string
  base_url: string
  domain: string
  created_by: string
  created_at: string
  updated_at: string
}

export type WebsiteKeyword = {
  id: string
  website_id: string
  keyword: string
  is_active: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export type SerpScanStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "canceled"

export type SerpScan = {
  id: string
  website_id: string
  status: SerpScanStatus
  requested_by: string
  market: string
  total_keywords: number
  processed_keywords: number
  failed_keywords: number
  max_requests_per_scan: number
  skipped_due_to_limit: number
  truncated_by_limit: boolean
  error_message: string | null
  created_at: string
  updated_at: string
}

export type StartWebsiteScanResponse = {
  scan_id: string
  status: SerpScanStatus
  total_keywords: number
  max_requests_per_scan: number
  skipped_due_to_limit: number
  truncated_by_limit: boolean
}

export type WebsiteRanking = {
  keyword_id: string
  keyword: string
  is_active: boolean
  current_position: number | null
  previous_position: number | null
  delta: number | null
  current_result_url: string | null
  current_matched_host: string | null
  last_scanned_at: string | null
  latest_scan_id: string | null
}

export type MetaRunStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "canceled"

export type MetaPageReviewStatus = "pending_review" | "approved" | "rejected"

export type MetaRun = {
  id: string
  website_id: string
  status: MetaRunStatus
  requested_by: string
  source: string
  total_pages: number
  processed_pages: number
  failed_pages: number
  max_pages_per_run: number
  skipped_due_to_limit: number
  include_paths: string[]
  exclude_paths: string[]
  error_message: string | null
  created_at: string
  updated_at: string
}

export type MetaPageItem = {
  id: string
  run_id: string
  website_id: string
  url: string
  path: string
  current_title: string | null
  current_description: string | null
  suggested_title: string | null
  suggested_description: string | null
  approved_title: string | null
  approved_description: string | null
  review_status: MetaPageReviewStatus
  generation_error: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
}

export type StartMetaRunResponse = {
  run_id: string
  status: MetaRunStatus
  total_pages: number
  max_pages_per_run: number
  skipped_due_to_limit: number
}
