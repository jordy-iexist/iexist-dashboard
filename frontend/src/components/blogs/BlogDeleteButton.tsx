"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"

type Props = {
  blogId: string
}

export function BlogDeleteButton({ blogId }: Props) {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    if (!window.confirm("Weet je zeker dat je deze blog wilt verwijderen?")) {
      return
    }

    setDeleting(true)
    setError(null)

    try {
      const response = await fetch(`/api/blogs/${blogId}`, {
        method: "DELETE",
      })

      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as
          | { error?: string }
          | null
        setError(data?.error ?? "Kon blog niet verwijderen.")
        return
      }

      router.push("/dashboard/blogs")
    } catch {
      setError("Er is een fout opgetreden.")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div>
      <Button
        variant="destructive"
        size="sm"
        onClick={handleDelete}
        disabled={deleting}
      >
        {deleting ? "Verwijderen..." : "Verwijder blog"}
      </Button>
      {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
    </div>
  )
}
