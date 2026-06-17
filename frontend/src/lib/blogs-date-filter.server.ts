import { cookies } from "next/headers"

import {
  BLOGS_CREATED_DATE_COOKIE,
  type CreatedDateParams,
} from "@/lib/blogs-date-filter"

const EMPTY_CREATED_DATE: CreatedDateParams = {
  createdOn: null,
  createdFrom: null,
  createdTo: null,
}

function isValidIsoInstant(value: unknown): value is string {
  if (typeof value !== "string" || value.trim().length === 0) {
    return false
  }
  return !Number.isNaN(new Date(value).getTime())
}

// Leest de onthouden datumselectie uit de cookie. De client schrijft de
// UTC-grenzen weg in de lokale tijdzone van de browser; de server valideert
// hier alleen en blijft timezone-agnostisch.
export async function readCreatedDateCookie(): Promise<CreatedDateParams> {
  const cookieStore = await cookies()
  const raw = cookieStore.get(BLOGS_CREATED_DATE_COOKIE)?.value
  if (!raw) {
    return EMPTY_CREATED_DATE
  }

  try {
    const parsed = JSON.parse(decodeURIComponent(raw)) as Partial<CreatedDateParams>
    const createdOn = parsed.createdOn
    if (typeof createdOn !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(createdOn)) {
      return EMPTY_CREATED_DATE
    }
    if (!isValidIsoInstant(parsed.createdFrom) || !isValidIsoInstant(parsed.createdTo)) {
      return EMPTY_CREATED_DATE
    }
    return {
      createdOn,
      createdFrom: parsed.createdFrom,
      createdTo: parsed.createdTo,
    }
  } catch {
    return EMPTY_CREATED_DATE
  }
}
