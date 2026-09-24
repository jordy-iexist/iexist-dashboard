import { cookies } from "next/headers"

import { BLOGS_VIEW_COOKIE, type BlogsView } from "@/lib/blogs-view"

// Leest de onthouden weergave uit de cookie; standaard de lijstweergave.
export async function readBlogsViewCookie(): Promise<BlogsView> {
  const cookieStore = await cookies()
  return cookieStore.get(BLOGS_VIEW_COOKIE)?.value === "grid" ? "grid" : "list"
}
