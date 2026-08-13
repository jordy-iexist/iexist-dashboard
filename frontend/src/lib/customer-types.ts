export type CustomerWebsiteItem = {
  id: string
  name: string
  base_url: string
  domain: string
  seo_customer_since: string | null
  seo_goals: string | null
  category_id: string | null
  category_name: string | null
  target_blogs_per_month: number | null
  target_links_per_month: number | null
  spreadsheet_url: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type CustomerWebsiteDetail = CustomerWebsiteItem & {
  placed_this_month: number
  links_placed_this_month: number
  pending_blogs: number | null
}

export type CustomerWebsiteListItem = CustomerWebsiteItem & {
  placed_this_month: number
  links_placed_this_month: number
}

export type CustomersResponse = {
  websites: CustomerWebsiteListItem[]
}

export type CustomerCategory = {
  id: string
  name: string
  customer_count: number
}

export type CustomerCategoriesResponse = {
  categories: CustomerCategory[]
}
