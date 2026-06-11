"use client"

import { useRouter } from "next/navigation"

export type CustomerFilterOption = {
  id: string
  name: string
}

export function CustomerFilterSelect({
  customers,
  selected,
  scope,
  basePath,
  extraParams,
}: {
  customers: CustomerFilterOption[]
  selected: string | null
  scope: string
  basePath: string
  extraParams?: Record<string, string>
}) {
  const router = useRouter()

  const onChange = (value: string) => {
    const params = new URLSearchParams()
    if (scope !== "all") {
      params.set("scope", scope)
    }
    if (value) {
      params.set("customer_website_id", value)
    }
    for (const [key, paramValue] of Object.entries(extraParams ?? {})) {
      if (paramValue) {
        params.set(key, paramValue)
      }
    }
    const query = params.toString()
    router.push(query ? `${basePath}?${query}` : basePath)
  }

  return (
    <select
      value={selected ?? ""}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Filter op klant"
      className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option value="">Alle klanten</option>
      <option value="none">Zonder klant</option>
      {customers.map((customer) => (
        <option key={customer.id} value={customer.id}>
          {customer.name}
        </option>
      ))}
    </select>
  )
}
