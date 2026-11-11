"use client"

import { useEffect, useRef } from "react"

/**
 * Roept `tick` elke `intervalMs` aan zolang `enabled` waar is.
 *
 * Een ronde wordt overgeslagen als de vorige nog loopt of het tabblad
 * verborgen is. Een fout in `tick` stopt het pollen niet: de volgende ronde
 * probeert het opnieuw.
 */
export function usePolling(tick: () => Promise<unknown>, enabled: boolean, intervalMs: number) {
  const tickRef = useRef(tick)

  useEffect(() => {
    tickRef.current = tick
  }, [tick])

  useEffect(() => {
    if (!enabled) return
    let running = false
    const timer = setInterval(async () => {
      if (running || document.hidden) return
      running = true
      try {
        await tickRef.current()
      } catch {
        // tijdelijke fout: volgende ronde opnieuw
      } finally {
        running = false
      }
    }, intervalMs)
    return () => clearInterval(timer)
  }, [enabled, intervalMs])
}
