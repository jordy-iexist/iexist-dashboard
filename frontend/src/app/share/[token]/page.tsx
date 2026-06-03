import { notFound } from "next/navigation"
import { unstable_noStore as noStore } from "next/cache"

import { SharedBlogView } from "@/components/blogs/SharedBlogView"
import { getBackendApiUrl } from "@/lib/backend-api"
import { type BlogSharePayload } from "@/lib/blog-types"

type SharePageProps = {
  params: Promise<{ token: string }>
}

export const metadata = {
  title: "Blog bekijken",
}

export default async function SharePage({ params }: SharePageProps) {
  noStore()

  const { token } = await params

  let payload: BlogSharePayload | null = null
  try {
    const response = await fetch(
      `${getBackendApiUrl()}/api/blogs/share/${encodeURIComponent(token)}`,
      { cache: "no-store" }
    )

    if (!response.ok) {
      notFound()
    }

    payload = (await response.json().catch(() => null)) as BlogSharePayload | null
  } catch {
    notFound()
  }

  if (!payload?.id) {
    notFound()
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4">
        <span className="text-sm font-semibold tracking-tight">iExist</span>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10">
        <SharedBlogView
          content={payload.content}
          images={payload.images}
          createdAt={payload.created_at}
        />
      </main>
    </div>
  )
}
