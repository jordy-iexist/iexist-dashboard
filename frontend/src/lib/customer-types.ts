export type CustomerWebsiteItem = {
  id: string
  name: string
  base_url: string
  domain: string
  is_active: boolean
  seo_customer_since: string | null
  seo_goals: string | null
  industry: string | null
  target_blogs_per_month: number | null
  created_by: string
  created_at: string
  updated_at: string
}

export type CustomerWebsiteDetail = CustomerWebsiteItem & {
  placed_this_month: number
  pending_blogs: number | null
}

export type CustomersResponse = {
  websites: CustomerWebsiteItem[]
}
