"use client"

import { useEffect, useState } from "react"

type RequestResult<T> = { key: string; data?: T; error?: string }

export type RequestState<T> = {
  /** Data van de huidige sleutel, of (tijdens herladen) van de vorige: dan is `loading` true. */
  data: T | null
  error: string | null
  loading: boolean
}

/**
 * Haalt data op voor `key` (`null` = niets ophalen). Bij een nieuwe sleutel
 * wordt de vorige aanvraag afgebroken, zodat een trage oude respons een nieuwe
 * keuze nooit overschrijft. De vorige data blijft staan tot de nieuwe binnen is
 * (geen leeg scherm bij wisselen).
 */
export function useRequest<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): RequestState<T> {
  const [result, setResult] = useState<RequestResult<T> | null>(null)

  useEffect(() => {
    if (key === null) return
    const controller = new AbortController()
    load(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setResult({ key, data })
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setResult({ key, error: err.message || "Er ging iets mis." })
      })
    return () => controller.abort()
    // `load` hangt alleen af van wat in `key` zit; zo hoeven aanroepers hem niet te memoïseren.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  if (key === null) return { data: null, error: null, loading: false }
  const current = result?.key === key
  return {
    data: result?.data ?? null,
    error: current ? (result?.error ?? null) : null,
    loading: !current,
  }
}
