"use client"

import { Check, ExternalLink, Minus, X } from "lucide-react"
import { useState } from "react"

import { useRequest } from "@/components/analytics/compare/use-request"
import { ErrorNote, Notice } from "@/components/analytics/states"
import { formatNumber, SectionTitle, Table, td, tdRight, th, thRight } from "@/components/livegang/comparison-parts"
import { CompactStat, PanelRow, Pill, StatGrid } from "@/components/livegang/shared"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  apiFetch,
  formatDateTime,
  PRT_PLATFORMS,
  type PrtLink,
  type PrtPlatformDetail,
  type PrtPrompt,
  type PrtPromptDetail,
  type PrtPromptStatus,
  type ProRankTrackerSnapshot,
} from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

/** AI-zichtbaarheid uit ProRankTracker: hoe vaak de site getoond, genoemd en gelinkt wordt in AI-antwoorden. */
export function AiVisibilityTab({
  scanId,
  snapshot,
}: {
  scanId: string
  snapshot: ProRankTrackerSnapshot | null | undefined
}) {
  const [selected, setSelected] = useState<PrtPrompt | null>(null)

  if (!snapshot) {
    return (
      <PanelRow tone="muted" className="text-muted-foreground">
        Deze scan is gemaakt vóór de ProRankTracker-koppeling en bevat daarom geen AI-zichtbaarheid. Een nieuwe scan
        haalt deze cijfers op.
      </PanelRow>
    )
  }

  if (snapshot.state === "not_tracked") {
    return (
      <PanelRow tone="muted" className="text-muted-foreground">
        Deze site wordt (nog) niet getrackt in ProRankTracker. URL&apos;s en prompts voeg je toe in ProRankTracker zelf;
        de eerstvolgende scan haalt de cijfers daarna op.
      </PanelRow>
    )
  }

  if (snapshot.state === "not_configured") {
    return (
      <PanelRow tone="muted" className="text-muted-foreground">
        ProRankTracker is niet gekoppeld: het API-token ontbreekt op de server. Na het instellen haalt de volgende scan
        de AI-zichtbaarheid op.
      </PanelRow>
    )
  }

  if (snapshot.state === "error" || !snapshot.totals || !snapshot.platforms) {
    return (
      <PanelRow tone="error">
        ProRankTracker kon niet worden uitgelezen: {snapshot.message ?? "onbekende fout"}
      </PanelRow>
    )
  }

  const { totals, platforms } = snapshot
  // Hoogste score eerst; prompts zonder score onderaan.
  const prompts = [...snapshot.prompts].sort((a, b) => (b.visibility ?? -1) - (a.visibility ?? -1))

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        {snapshot.url ? (
          <>
            Getrackte URL:{" "}
            <a
              href={snapshot.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 break-all text-primary hover:underline"
            >
              {snapshot.url} <ExternalLink className="size-3 shrink-0" />
            </a>
          </>
        ) : (
          "Getrackt in ProRankTracker"
        )}{" "}
        · opgehaald {formatDateTime(snapshot.fetched_at)}
      </p>

      {snapshot.errors.length > 0 && (
        <PanelRow tone="warning">
          <ul className="space-y-1 text-xs">
            {snapshot.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </PanelRow>
      )}

      <StatGrid className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        <CompactStat
          label="AI-zichtbaarheid"
          value={
            totals.visibility == null ? (
              "—"
            ) : (
              <>
                {formatNumber(totals.visibility, 1)}
                <span className="text-sm font-normal text-muted-foreground"> /100</span>
              </>
            )
          }
          hint="Score over alle prompts en platformen"
        />
        <CompactStat label="Vertoningen" value={formatNumber(totals.appearances)} hint="Keer getoond in een AI-antwoord" />
        <CompactStat label="Vermeldingen" value={formatNumber(totals.mentions)} hint="Keer bij naam genoemd" />
        <CompactStat
          label="Links"
          value={formatNumber(totals.links)}
          hint={totals.links_avg != null ? `Gem. positie ${formatNumber(totals.links_avg, 1)}` : undefined}
        />
        <CompactStat label="Prompts" value={formatNumber(totals.prompts)} hint="Getrackt in ProRankTracker" />
      </StatGrid>

      <section className="space-y-2">
        <SectionTitle>Per platform</SectionTitle>
        <Table
          head={
            <tr>
              <th className={th}>Platform</th>
              <th className={thRight}>Zichtbaarheid</th>
              <th className={th}>Getoond bij</th>
              <th className={thRight}>Vermeldingen</th>
              <th className={thRight}>Links</th>
              <th className={thRight}>Gem. linkpositie</th>
            </tr>
          }
        >
          {PRT_PLATFORMS.map(({ key, label }) => {
            const stats = platforms[key]
            const tracked = !!stats && stats.prompts_tracked > 0
            return (
              <tr key={key}>
                <td className={cn(td, "font-medium whitespace-nowrap")}>{label}</td>
                <td className={tdRight}>{tracked ? formatNumber(stats.visibility, 1) : "—"}</td>
                <td className={cn(td, "whitespace-nowrap")}>
                  {tracked ? (
                    `${stats.prompts_shown} van ${stats.prompts_tracked} prompts`
                  ) : (
                    <span className="text-muted-foreground">niet getrackt</span>
                  )}
                </td>
                <td className={tdRight}>{tracked ? formatNumber(stats.mentions) : "—"}</td>
                <td className={tdRight}>{tracked ? formatNumber(stats.links) : "—"}</td>
                <td className={tdRight}>{tracked ? formatNumber(stats.links_avg, 1) : "—"}</td>
              </tr>
            )
          })}
        </Table>
      </section>

      <section className="space-y-2">
        <SectionTitle>Prompts</SectionTitle>
        {prompts.length === 0 ? (
          <p className="text-sm text-muted-foreground">Er staan voor deze site nog geen prompts in ProRankTracker.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>Klik op een prompt voor het actuele antwoord per platform.</span>
              <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Legenda">
                <span className="inline-flex items-center gap-1">
                  <StatusDot status="shown" /> getoond
                </span>
                <span className="inline-flex items-center gap-1">
                  <StatusDot status="not_shown" /> niet getoond
                </span>
                <span className="inline-flex items-center gap-1">
                  <StatusDot status="not_added" /> niet toegevoegd
                </span>
              </span>
            </div>
            <Table
              head={
                <tr>
                  <th className={th}>Prompt</th>
                  <th className={thRight}>Score</th>
                  {PRT_PLATFORMS.map((p) => (
                    <th key={p.key} className="px-2 py-2 text-center text-[11px] font-medium whitespace-nowrap">
                      {p.label}
                    </th>
                  ))}
                  <th className={thRight}>Vermeldingen</th>
                  <th className={thRight}>Links</th>
                  <th className={th}>Verloop</th>
                </tr>
              }
            >
              {prompts.map((prompt) => (
                <tr
                  key={prompt.prompt_id}
                  onClick={() => setSelected(prompt)}
                  className="cursor-pointer hover:bg-muted/40"
                >
                  <td className={cn(td, "min-w-64 max-w-md")}>
                    {/* De knop maakt de rij met het toetsenbord bereikbaar; de hele rij is klikbaar. */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelected(prompt)
                      }}
                      className="w-full rounded-sm text-left font-medium whitespace-normal hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      {prompt.prompt}
                    </button>
                    {(prompt.location || prompt.lang) && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {[prompt.location, prompt.lang].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </td>
                  <td className={cn(tdRight, "font-medium")}>{formatNumber(prompt.visibility, 1)}</td>
                  {PRT_PLATFORMS.map((p) => {
                    const entry = prompt.platforms?.[p.key]
                    return (
                      <td key={p.key} className="px-2 py-2 text-center">
                        <StatusDot status={entry?.status ?? "not_added"} count={entry?.count} platform={p.label} />
                      </td>
                    )
                  })}
                  <td className={tdRight}>{formatNumber(prompt.mentions)}</td>
                  <td className={tdRight}>{formatNumber(prompt.links)}</td>
                  <td className={td}>
                    <Sparkline values={prompt.trend} />
                  </td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </section>

      <PromptDetailSheet scanId={scanId} prompt={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

const STATUS_TEXT: Record<PrtPromptStatus, string> = {
  shown: "getoond",
  not_shown: "niet getoond",
  not_added: "niet toegevoegd",
}

/** Status per platform: vorm en icoon verschillen, zodat het niet alleen op kleur leunt. */
function StatusDot({ status, count, platform }: { status: PrtPromptStatus; count?: number; platform?: string }) {
  const text = `${platform ? `${platform}: ` : ""}${STATUS_TEXT[status]}${status === "shown" && count ? ` (${count}×)` : ""}`
  return (
    <span
      role="img"
      aria-label={text}
      title={text}
      className={cn(
        "inline-flex size-5 items-center justify-center rounded-full align-middle",
        status === "shown" && "bg-green-600 text-white dark:bg-green-500",
        status === "not_shown" && "border border-red-400 text-red-600 dark:border-red-500/70 dark:text-red-400",
        status === "not_added" && "border border-dashed border-muted-foreground/40 text-muted-foreground/50"
      )}
    >
      {status === "shown" ? (
        <Check className="size-3" strokeWidth={3} />
      ) : status === "not_shown" ? (
        <X className="size-3" strokeWidth={3} />
      ) : (
        <Minus className="size-3" />
      )}
    </span>
  )
}

/** Klein verloop van de score (inline SVG); 0 punten = streepje, 1 punt = stip. */
function Sparkline({ values }: { values: number[] | null | undefined }) {
  const points = (values ?? []).filter((v) => typeof v === "number" && Number.isFinite(v))
  if (points.length === 0) return <span className="text-muted-foreground">—</span>

  const width = 64
  const height = 20
  const pad = 2
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min
  const x = (i: number) => (points.length === 1 ? width / 2 : pad + (i * (width - 2 * pad)) / (points.length - 1))
  // Gelijke waarden: vlakke lijn in het midden.
  const y = (v: number) => (range === 0 ? height / 2 : height - pad - ((v - min) / range) * (height - 2 * pad))
  const label = `Verloop: ${formatNumber(points[0], 1)} → ${formatNumber(points[points.length - 1], 1)} (${points.length} metingen)`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="text-primary">
      <title>{label}</title>
      {points.length === 1 ? (
        <circle cx={x(0)} cy={y(points[0])} r={2} className="fill-current" />
      ) : (
        <>
          <polyline
            points={points.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
            fill="none"
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            className="stroke-current"
          />
          <circle cx={x(points.length - 1)} cy={y(points[points.length - 1])} r={2} className="fill-current" />
        </>
      )}
    </svg>
  )
}

// --- detail per prompt (live) -------------------------------------------------

function PromptDetailSheet({ scanId, prompt, onClose }: { scanId: string; prompt: PrtPrompt | null; onClose: () => void }) {
  const promptId = prompt?.prompt_id ?? null
  const { data, error, loading } = useRequest<PrtPromptDetail>(
    promptId === null ? null : `prt:${scanId}:${promptId}`,
    (signal) => apiFetch<PrtPromptDetail>(`/scans/${scanId}/proranktracker/prompts/${promptId}`, { signal })
  )
  // useRequest houdt de vorige data vast tijdens herladen: alleen tonen als hij bij deze prompt hoort.
  const detail = data && data.prompt_id === promptId ? data : null

  return (
    <Sheet open={prompt !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        {prompt && (
          <>
            <SheetHeader>
              <SheetTitle className="pr-6 leading-snug">{prompt.prompt}</SheetTitle>
              <SheetDescription>
                {[prompt.location, prompt.lang].filter(Boolean).join(" · ") || "AI-antwoorden per platform"}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              <Notice>
                Actueel antwoord, live uit ProRankTracker — dit is niet de stand op het moment van de scan.
                {detail && ` Opgehaald ${formatDateTime(detail.fetched_at)}.`}
              </Notice>
              {error ? (
                <ErrorNote>{error}</ErrorNote>
              ) : !detail ? (
                <p className="text-sm text-muted-foreground" aria-busy={loading}>
                  Laden…
                </p>
              ) : (
                detail.platforms.map((platform) => <PlatformSection key={platform.platform} platform={platform} />)
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

const ANSWER_COLLAPSE_AT = 600

function PlatformSection({ platform }: { platform: PrtPlatformDetail }) {
  const [expanded, setExpanded] = useState(false)

  if (!platform.tracked) {
    return (
      <section className="rounded-lg border bg-card px-4 py-3 text-sm">
        <span className="font-medium">{platform.label}</span>
        <span className="text-muted-foreground"> — deze prompt wordt op dit platform niet getrackt.</span>
      </section>
    )
  }

  const { mentions, links } = platform
  const mentioned = mentions.total > 0 || mentions.rank != null
  const ownLinks = links.items.filter((l) => l.is_own).length
  const linked = ownLinks > 0 || links.rank != null
  const sources = [...links.items].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
  const otherBrands = Object.entries(mentions.counts ?? {}).sort((a, b) => b[1] - a[1])
  const answer = platform.answer_text?.trim() ?? ""
  const long = answer.length > ANSWER_COLLAPSE_AT

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="mr-auto font-semibold">{platform.label}</h3>
        <Pill tone={mentioned ? "green" : "muted"}>
          {mentioned ? `Genoemd${mentions.total ? ` (${mentions.total}×)` : ""}` : "Niet genoemd"}
          {mentions.rank != null && ` · positie ${mentions.rank}`}
        </Pill>
        <Pill tone={linked ? "green" : "muted"}>
          {linked ? `Gelinkt${ownLinks ? ` (${ownLinks}×)` : ""}` : "Niet gelinkt"}
          {links.rank != null && ` · positie ${links.rank}`}
        </Pill>
      </div>

      {mentions.items.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Vermeldingen</p>
          <ul className="space-y-1.5 text-sm">
            {mentions.items.map((item, i) => (
              <li key={i} className="border-l-2 border-muted pl-3">
                <HighlightBrand text={item.sentence} brand={item.brand} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {otherBrands.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Genoemde merken</p>
          <div className="flex flex-wrap gap-1.5">
            {otherBrands.map(([brand, count]) => (
              <Pill key={brand}>
                {brand} · {count}×
              </Pill>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Antwoord</p>
        {answer ? (
          <>
            <pre
              className={cn(
                "rounded-md bg-muted/50 p-3 font-sans text-sm leading-6 break-words whitespace-pre-wrap",
                long && !expanded && "max-h-48 overflow-hidden"
              )}
            >
              {answer}
            </pre>
            {long && (
              <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
                {expanded ? "Minder tonen" : "Toon volledig antwoord"}
              </Button>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Geen antwoordtekst beschikbaar.</p>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-xs font-medium text-muted-foreground">Bronnen{sources.length ? ` (${sources.length})` : ""}</p>
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">Geen bronnen of links in dit antwoord.</p>
        ) : (
          <ol className="divide-y rounded-md border text-sm">
            {sources.map((link, i) => (
              <SourceRow key={`${link.url}-${i}`} link={link} />
            ))}
          </ol>
        )}
      </div>
    </section>
  )
}

function SourceRow({ link }: { link: PrtLink }) {
  const host = hostOf(link.url)
  return (
    <li className={cn("flex items-start gap-3 px-3 py-2", link.is_own && "bg-green-50 dark:bg-green-900/20")}>
      <span className="w-6 shrink-0 pt-0.5 text-right text-xs text-muted-foreground tabular-nums">
        {link.rank ?? "—"}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <a
          href={link.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex max-w-full items-start gap-1 font-medium break-words hover:text-primary hover:underline"
        >
          <span className="min-w-0">{link.title || host}</span>
          <ExternalLink className="mt-1 size-3 shrink-0" />
        </a>
        <p className="truncate text-xs text-muted-foreground" title={link.url}>
          {host}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap justify-end gap-1">
        {link.is_own && <Pill tone="green">eigen site</Pill>}
        {link.kind && <Pill tone={link.kind === "citation" ? "blue" : "muted"}>{link.kind === "citation" ? "bron" : "link"}</Pill>}
      </div>
    </li>
  )
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

/** Zet de merknaam in de zin in een markering (hoofdletterongevoelig). */
function HighlightBrand({ text, brand }: { text: string; brand: string }) {
  const name = brand?.trim()
  if (!name) return <>{text}</>
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const parts = text.split(new RegExp(`(${escaped})`, "gi"))
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-sm bg-amber-100 px-0.5 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
            {part}
          </mark>
        ) : (
          part
        )
      )}
    </>
  )
}
