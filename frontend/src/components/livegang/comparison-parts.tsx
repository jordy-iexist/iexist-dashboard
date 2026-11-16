/**
 * Bouwstenen en secties voor "voor tegen na"-vergelijkingen. Gebruikt door de
 * fase 4-tab Vergelijking (`QuarterlyDetails`) en door Analytics > Vergelijken
 * (scan A tegen B). De secties krijgen alleen het deel van de vergelijking dat
 * ze tonen, zodat ze met zowel `QuarterlyComparison` als de compare-respons werken.
 * Zonder `labels` tonen ze de teksten van de fase 4-tab ("Vorige"/"Nu").
 */
import { ArrowDown, ArrowUp, ExternalLink, Minus } from "lucide-react"

import { AutoStatusBadge, CompactStat, Pill, StatGrid } from "@/components/livegang/shared"
import { CATEGORY_LABELS, formatDateTime, type AiCheckChange, type QuarterlyComparison } from "@/lib/launch-checklist"
import { cn } from "@/lib/utils"

export type AiComparison = QuarterlyComparison["ai"]
export type IssuesComparison = QuarterlyComparison["issues"]
export type PagesComparison = QuarterlyComparison["pages"]
export type AhrefsComparison = NonNullable<QuarterlyComparison["ahrefs"]>
export type RankingsComparison = NonNullable<QuarterlyComparison["rankings"]>

/** Kolomkoppen voor de twee kanten van een vergelijking, bijv. de labels van scan A en B. */
export type CompareLabels = { before: string; after: string }

export const MAX_ROWS = 50
const linkClass = "inline-flex min-w-0 items-center gap-1 break-all text-primary hover:underline"

export function PageLink({ url, label }: { url: string; label?: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={linkClass}>
      <span className="truncate">{label ?? url}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}

export function formatNumber(value: number | null | undefined, digits = 0) {
  return value == null ? "—" : value.toLocaleString("nl-NL", { maximumFractionDigits: digits })
}

/** Verschil met pijl; `higherIsBetter` bepaalt de kleur. */
export function Delta({ value, higherIsBetter = true, digits = 0 }: { value: number | null | undefined; higherIsBetter?: boolean; digits?: number }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  if (value === 0) return <span className="inline-flex items-center gap-0.5 text-muted-foreground"><Minus className="size-3" />0</span>
  const good = value > 0 === higherIsBetter
  const Icon = value > 0 ? ArrowUp : ArrowDown
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-medium", good ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400")}>
      <Icon className="size-3" />
      {formatNumber(Math.abs(value), digits)}
    </span>
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>
}

export function Table({ head, children }: { head: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">{head}</thead>
        <tbody className="divide-y">{children}</tbody>
      </table>
    </div>
  )
}

export const th = "px-3 py-2 text-left font-medium"
export const thRight = "px-3 py-2 text-right font-medium"
export const td = "px-3 py-2"
export const tdRight = "px-3 py-2 text-right tabular-nums"

export const CHANGE_LABELS: Record<AiCheckChange["change"], { label: string; tone: "green" | "red" | "muted" | "blue" }> = {
  better: { label: "Verbeterd", tone: "green" },
  worse: { label: "Verslechterd", tone: "red" },
  same: { label: "Gelijk", tone: "muted" },
  new: { label: "Nieuw", tone: "blue" },
}

// --- secties -----------------------------------------------------------------------

/** Kerncijfers: AI-score, actiepunten en pagina's. Delen die ontbreken (`null`) vallen weg. */
export function ComparisonSummary({
  title,
  subtitle,
  ai,
  issues,
  pages,
  labels,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  ai: AiComparison | null
  issues: IssuesComparison | null
  pages: PagesComparison | null
  labels?: CompareLabels
}) {
  const was = (value: React.ReactNode) => (labels ? `${labels.before}: ${value}` : `was ${value}`)
  const aiDelta = ai && ai.before != null && ai.after != null ? ai.after - ai.before : null
  return (
    <section className="space-y-2">
      <SectionTitle>{title}</SectionTitle>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      <StatGrid className="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        {ai && (
          <CompactStat
            label="AI-score"
            value={<span className="inline-flex items-baseline gap-2">{ai.after ?? "—"} <span className="text-xs"><Delta value={aiDelta} /></span></span>}
            hint={ai.before != null ? was(ai.before) : undefined}
          />
        )}
        {issues && (
          <CompactStat
            label="Actiepunten"
            value={<span className="inline-flex items-baseline gap-2">{issues.after} <span className="text-xs"><Delta value={issues.after - issues.before} higherIsBetter={false} /></span></span>}
            hint={`${was(issues.before)}${issues.not_compared ? ` · excl. ${issues.not_compared} uit nieuwe controles` : ""}`}
          />
        )}
        {pages && (
          <>
            <CompactStat label="Pagina's" value={pages.after} hint={was(pages.before)} />
            <CompactStat label="Nieuwe pagina's" value={pages.new} />
            <CompactStat label="Niet meer gevonden" value={pages.removed} tone={pages.removed ? "warn" : undefined} />
            <CompactStat label={labels ? "Kapot geworden" : "Nu kapot"} value={pages.broken} tone={pages.broken ? "bad" : "good"} />
          </>
        )}
      </StatGrid>
    </section>
  )
}

export function AiSection({ ai, labels }: { ai: AiComparison; labels?: CompareLabels }) {
  const checks = ai.checks
  if (!checks.length) return null
  return (
    <section className="space-y-2">
      <SectionTitle>AI-vindbaarheid</SectionTitle>
      <Table
        head={
          <tr>
            <th className={th}>Check</th>
            <th className={th}>{labels?.before ?? "Vorige"}</th>
            <th className={th}>{labels?.after ?? "Nu"}</th>
            <th className={th}>Verandering</th>
          </tr>
        }
      >
        {checks.map((check) => (
          <tr key={check.key}>
            <td className={td}>
              <p className="font-medium">{check.label}</p>
              {check.message && <p className="text-xs text-muted-foreground">{check.message}</p>}
            </td>
            <td className={td}><AutoStatusBadge status={check.before ?? undefined} /></td>
            <td className={td}><AutoStatusBadge status={check.after} /></td>
            <td className={td}><Pill tone={CHANGE_LABELS[check.change].tone}>{CHANGE_LABELS[check.change].label}</Pill></td>
          </tr>
        ))}
      </Table>
    </section>
  )
}

export function RankingsSection({
  rankings,
  labels,
  emptyText = "Geen posities: voor deze klant worden geen zoekwoorden gevolgd in de SEO-tracker.",
}: {
  rankings: RankingsComparison | null
  labels?: CompareLabels
  /** Tekst als er geen posities zijn. */
  emptyText?: string
}) {
  return (
    <section className="space-y-2">
      <SectionTitle>Posities (SEO-tracker)</SectionTitle>
      {!rankings ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <>
          <StatGrid className="grid-cols-2 sm:grid-cols-5">
            <CompactStat label="Zoekwoorden" value={rankings.keywords} />
            <CompactStat label="In top 3" value={rankings.top3} />
            <CompactStat label="In top 10" value={rankings.top10} />
            <CompactStat label="Gestegen" value={rankings.improved} tone={rankings.improved ? "good" : undefined} />
            <CompactStat label="Gedaald" value={rankings.declined} tone={rankings.declined ? "bad" : undefined} />
          </StatGrid>
          {rankings.compared === 0 && (
            <p className="text-xs text-muted-foreground">
              Er zijn geen metingen van vóór {labels ? labels.before : "de basisdatum"} om mee te vergelijken.
            </p>
          )}
          <Table
            head={
              <tr>
                <th className={th}>Zoekwoord</th>
                <th className={thRight}>{labels?.before ?? "Toen"}</th>
                <th className={thRight}>{labels?.after ?? "Nu"}</th>
                <th className={thRight}>Verschil</th>
                <th className={th}>Pagina</th>
              </tr>
            }
          >
            {rankings.rows.slice(0, MAX_ROWS).map((row) => (
              <tr key={row.keyword}>
                <td className={td}>{row.keyword}</td>
                <td className={tdRight}>{row.before ?? "—"}</td>
                <td className={tdRight}>{row.after ?? ">100"}</td>
                <td className={tdRight}><Delta value={row.delta} /></td>
                <td className={cn(td, "max-w-64")}>{row.url ? <PageLink url={row.url} /> : <span className="text-muted-foreground">—</span>}</td>
              </tr>
            ))}
          </Table>
          {rankings.last_checked_at && (
            <p className="text-xs text-muted-foreground">Laatste meting: {formatDateTime(rankings.last_checked_at)}.</p>
          )}
        </>
      )}
    </section>
  )
}

export function AhrefsSection({ ahrefs, labels }: { ahrefs: AhrefsComparison | null; labels?: CompareLabels }) {
  return (
    <section className="space-y-2">
      <SectionTitle>Backlinks &amp; autoriteit (Ahrefs)</SectionTitle>
      {!ahrefs ? (
        <p className="text-sm text-muted-foreground">
          {labels ? `Geen Ahrefs-data in ${labels.before} of ${labels.after}.` : "Geen Ahrefs-data in deze of de vorige scan."}
        </p>
      ) : (
        <>
          {ahrefs.same_snapshot && (
            <p className="text-xs text-muted-foreground">
              Dezelfde Ahrefs-meting als {labels ? labels.before : "de basis"} ({formatDateTime(ahrefs.fetched_after)}): de data is hergebruikt binnen de
              bewaartermijn, dus er is nog geen verschil te zien.
            </p>
          )}
          <Table
            head={
              <tr>
                <th className={th}>Cijfer</th>
                <th className={thRight}>{labels?.before ?? "Vorige"}</th>
                <th className={thRight}>{labels?.after ?? "Nu"}</th>
                <th className={thRight}>Verschil</th>
              </tr>
            }
          >
            {ahrefs.metrics.map((metric) => (
              <tr key={metric.key}>
                <td className={td}>{metric.label}</td>
                <td className={tdRight}>{formatNumber(metric.before, 1)}</td>
                <td className={tdRight}>{formatNumber(metric.after, 1)}</td>
                <td className={tdRight}><Delta value={metric.delta} digits={1} /></td>
              </tr>
            ))}
          </Table>
          {!!ahrefs.lost_value_urls && (
            <p className="text-xs text-muted-foreground">
              {ahrefs.lost_value_urls} pagina&apos;s met verkeer of backlinks werken niet meer (zie de actiepunten).
            </p>
          )}
        </>
      )}
    </section>
  )
}

export function IssuesSection({ issues, labels }: { issues: IssuesComparison; labels?: CompareLabels }) {
  // Nieuwe controles (comparable false) altijd tonen: ze hebben geen 'vorige' om mee te vergelijken.
  const rows = issues.rows.filter((r) => r.comparable === false || r.delta !== 0)
  return (
    <section className="space-y-2">
      <SectionTitle>Veranderingen in actiepunten</SectionTitle>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Geen veranderingen in het aantal actiepunten per type.</p>
      ) : (
        <Table
          head={
            <tr>
              <th className={th}>Type</th>
              <th className={th}>Categorie</th>
              <th className={thRight}>{labels?.before ?? "Vorige"}</th>
              <th className={thRight}>{labels?.after ?? "Nu"}</th>
              <th className={thRight}>Verschil</th>
            </tr>
          }
        >
          {rows.slice(0, MAX_ROWS).map((row) => {
            const isNew = row.comparable === false || row.before == null
            return (
              <tr key={row.issue_type}>
                <td className={td}>{row.label}</td>
                <td className={cn(td, "text-xs text-muted-foreground")}>{CATEGORY_LABELS[row.category] ?? row.category}</td>
                <td className={tdRight}>{isNew ? <NewCheck base={labels?.before} /> : row.before}</td>
                <td className={tdRight}>{row.after}</td>
                <td className={tdRight}>{isNew ? <NewCheck base={labels?.before} /> : <Delta value={row.delta} higherIsBetter={false} />}</td>
              </tr>
            )
          })}
        </Table>
      )}
    </section>
  )
}

/** Actiepunttype dat de basis-scan nog niet (of anders) controleerde: geen voor/na-vergelijking. */
function NewCheck({ base }: { base?: string }) {
  return (
    <span
      className="text-xs text-muted-foreground"
      title={`${base ? `De scan ${base}` : "De basis-scan"} deed deze controle nog niet, of mat hem op een andere manier`}
    >
      nieuwe controle
    </span>
  )
}
