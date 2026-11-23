import { cookies } from "next/headers"

import { ACTIVE_CUSTOMER_COOKIE } from "@/lib/active-customer"

// Leest de laatst gekozen klant uit de cookie; null als er geen is.
export async function readActiveCustomerCookie(): Promise<string | null> {
  const cookieStore = await cookies()
  const raw = cookieStore.get(ACTIVE_CUSTOMER_COOKIE)?.value
  if (!raw) return null
  let value = raw
  try {
    value = decodeURIComponent(raw)
  } catch {
    // ongeldige codering: gebruik de ruwe waarde
  }
  value = value.trim()
  return value && value !== "none" ? value : null
}
