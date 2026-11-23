"use client"

import { useRef, useState, useTransition } from "react"
import { useRouter } from "next/navigation"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// Haalt de Quick wins opnieuw op uit Ahrefs en ververst daarna de pagina.
export function RefreshQuickWinsButton({ customerId }: { customerId: string }) {
  const router = useRouter()
  const [isPosting, setIsPosting] = useState(false)
  const [isRefreshing, startTransition] = useTransition()
  const [error, setError] = useState<string | null>(null)
  // Ref naast de state: blokkeert een tweede klik nog voordat de render met `disabled` er is.
  const busyRef = useRef(false)

  const busy = isPosting || isRefreshing

  const refresh = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setIsPosting(true)
    setError(null)
    try {
      const response = await fetch(
        `/api/customers/${encodeURIComponent(customerId)}/quick-wins/refresh`,
        { method: "POST" }
      )
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as
          | { error?: unknown }
          | null
        throw new Error(
          typeof payload?.error === "string" && payload.error
            ? payload.error
            : "Vernieuwen is mislukt."
        )
      }
      startTransition(() => {
        router.refresh()
      })
    } catch (caught) {
      setError(
        caught instanceof Error && caught.message
          ? caught.message
          : "Vernieuwen is mislukt."
      )
    } finally {
      busyRef.current = false
      setIsPosting(false)
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        size="sm"
        variant="secondary"
        onClick={refresh}
        disabled={busy}
        aria-busy={busy}
        title="Haalt de zoekwoorden opnieuw op uit Ahrefs (kost Ahrefs-units)"
      >
        <RefreshCw className={cn(busy && "animate-spin")} aria-hidden="true" />
        {busy ? "Vernieuwen…" : "Vernieuwen"}
      </Button>
      {error && (
        <p role="alert" className="max-w-xs text-right text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
