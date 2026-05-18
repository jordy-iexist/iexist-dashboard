export type AuditStatus =
  | "pending"
  | "crawling"
  | "scanning"
  | "completed"
  | "failed"
  | "canceled"

export type AuditSeverity = "critical" | "warning" | "info"

export type AuditCategory =
  | "typography"
  | "performance"
  | "accessibility"
  | "links"
  | "responsive"
  | "seo"
  | "console_error"
  | "functionality"

export interface AuditSummary {
  total_issues: number
  critical: number
  warnings: number
  info: number
  categories: Record<string, number>
  score: number
  typography_summary?: {
    unique_font_families: string[]
    pages_with_data: number
  }
}

export interface AuditItem {
  id: string
  url: string
  domain: string
  status: AuditStatus
  total_pages: number
  scanned_pages: number
  failed_pages: number
  max_pages: number
  crawl_source: string | null
  summary: AuditSummary | null
  error_message: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface AuditListResponse {
  items: AuditItem[]
  total: number
}

export interface AuditPageItem {
  id: string
  audit_id: string
  url: string
  path: string
  status: string
  issue_count: number
  typography_data: unknown
  performance_data: unknown
  accessibility_data: unknown
  console_errors: unknown
  meta_data: unknown
  links_data: unknown
  responsive_data: unknown
  screenshots?: { desktop?: string; mobile?: string } | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface AuditPageListResponse {
  pages: AuditPageItem[]
  total: number
}

export interface AuditIssueItem {
  id: string
  audit_id: string
  page_id: string | null
  category: AuditCategory
  severity: AuditSeverity
  title: string
  description: string
  selector: string | null
  page_url: string | null
  issue_metadata: unknown
  created_at: string
}

export interface AuditIssueListResponse {
  issues: AuditIssueItem[]
  total: number
}

export interface StartAuditResponse {
  audit_id: string
  status: AuditStatus
  url: string
}
