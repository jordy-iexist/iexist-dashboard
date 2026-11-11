import { CircleAlert, CircleCheck, CircleX } from "lucide-react"

import { Pill } from "@/components/livegang/shared"
import type { AiChecks } from "@/lib/launch-checklist"

const ICONS = {
  ok: <CircleCheck className="size-5 text-green-600" />,
  warning: <CircleAlert className="size-5 text-amber-500" />,
  error: <CircleX className="size-5 text-red-600" />,
}

export function AiChecksTab({ checks }: { checks: AiChecks | null }) {
  if (!checks) {
    return <p className="text-sm text-muted-foreground">De AI-vindbaarheidschecks zijn nog niet uitgevoerd.</p>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <p className="text-4xl font-bold text-primary">{checks.score}</p>
        <p className="text-sm text-muted-foreground">
          AI-vindbaarheidsscore
          <br />
          (ok = 1, waarschuwing = ½, fout = 0)
        </p>
      </div>

      <ul className="grid gap-3 md:grid-cols-2">
        {checks.checks.map((check) => (
          <li key={check.key} className="flex gap-3 rounded-lg border bg-card p-4">
            {ICONS[check.status]}
            <div className="min-w-0 space-y-1">
              <p className="font-medium">{check.label}</p>
              <p className="text-sm text-muted-foreground">{check.message}</p>
            </div>
          </li>
        ))}
      </ul>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Toegang per bot (robots.txt, homepage)
        </h3>
        <div className="flex flex-wrap gap-2">
          {checks.bots.map((bot) => (
            <Pill key={bot.bot} tone={bot.allowed ? "green" : "red"}>
              <span className="font-mono">{bot.bot}</span>
              <span className="opacity-70">· {bot.label}</span>
            </Pill>
          ))}
        </div>
      </section>
    </div>
  )
}
