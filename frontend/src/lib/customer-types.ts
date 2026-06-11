export type CustomerWebsiteItem = {
  id: string
  name: string
  base_url: string
  domain: string
  is_active: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export type CustomersResponse = {
  websites: CustomerWebsiteItem[]
}
