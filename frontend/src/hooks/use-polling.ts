"use client"

import { useEffect, useRef, useState } from "react"

/** Na zoveel mislukte rondes op rij melden we dat de status niet meer bijwerkt. */
const FAILURES_BEFORE_NOTICE = 3

/**
 * Roept `tick` elke `intervalMs` aan zolang `enabled` waar is.
 *
 * Een ronde wordt overgeslagen als de vorige nog loopt of het tabblad
 * verborgen is. Een fout in `tick` stopt het pollen niet: de volgende ronde
 * probeert het opnieuw. Na drie mislukte rondes op rij is `failing` waar, tot
 * een ronde weer slaagt of het pollen stopt.
 */
export function usePolling(tick: () => Promise<unknown>, enabled: boolean, intervalMs: number) {
  const tickRef = useRef(tick)
  const [failing, setFailing] = useState(false)

  useEffect(() => {
    tickRef.current = tick
  }, [tick])

  useEffect(() => {
    if (!enabled) return
    let running = false
    let failures = 0
    const timer = setInterval(async () => {
      if (running || document.hidden) return
      running = true
      try {
        await tickRef.current()
        failures = 0
        setFailing(false)
      } catch {
        // tijdelijke fout: volgende ronde opnieuw
        failures += 1
        if (failures >= FAILURES_BEFORE_NOTICE) setFailing(true)
      } finally {
        running = false
      }
    }, intervalMs)
    return () => {
      clearInterval(timer)
      // Gestopt of opnieuw gestart: de teller begint opnieuw.
      setFailing(false)
    }
  }, [enabled, intervalMs])

  // Een ronde die nog liep toen het pollen stopte, kan `failing` daarna nog zetten.
  return { failing: enabled && failing }
}
