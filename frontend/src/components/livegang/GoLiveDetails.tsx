"use client"

import { ArrowRight, ExternalLink } from "lucide-react"

import { AutoStatusBadge, HttpStatusBadge, Pill } from "@/components/livegang/shared"
import type { ChecklistItem, GoLiveDetails, GoLiveHop, GoLiveUrlRow, GoLiveVariant } from "@/lib/launch-checklist"

const MAX_ROWS = 25
const linkClass = "inline-flex min-w-0 items-center gap-1 break-all text-primary hover:underline"

const REF_TYPE_LABELS: Record<string, string> = {
  canonical: "canonical",
  og_url: "og:url",
  hreflang: "hreflang",
  link: "link",
  asset: "bestand",
  form: "formulier",
  inline: "inline CSS/JS",
  sitemap: "sitemap",
}

const ISSUE_LABELS: Record<string, string> = {
  http: "http://",
  host: "andere hostvariant",
  "http+host": "http:// en andere hostvariant",
}

function UrlLink({ url, label }: { url: string; label?: string }) {
  if (!/^https?:\/\//.test(url)) return <span className="break-all">{label ?? url}</span>
  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={linkClass}>
      <span className="truncate">{label ?? url}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}

function pathOf(url: string) {
  try {
    const parsed = new URL(url)
    return parsed.pathname + parsed.search
  } catch {
    return url
  }
}

/** "(en nog N)" als de lijst gecapt is. */
function More({ total, shown }: { total: number | undefined; shown: number }) {
  if (!total || total <= shown) return null
  return <p className="text-muted-foreground">En nog {total - shown}.</p>
}

function Heading({ children }: { children: React.ReactNode }) {
  return <p className="mb-1 font-medium text-muted-foreground">{children}</p>
}

function RowList({ children }: { children: React.ReactNode }) {
  return <ul className="divide-y rounded-md border bg-card">{children}</ul>
}

function Chain({ chain, finalUrl, finalStatus, error }: {
  chain: GoLiveHop[]
  finalUrl: string | null
  finalStatus: number | null
  error: string | null
}) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1">
      {chain.map((hop, index) => (
        <span key={index} className="inline-flex items-center gap-1">
          <HttpStatusBadge status={hop.status} />
          <ArrowRight className="size-3 text-muted-foreground" />
        </span>
      ))}
      {error ? (
        <span className="text-red-700 dark:text-red-400">{error}</span>
      ) : (
        <>
          <HttpStatusBadge status={finalStatus} />
          {finalUrl && <span className="break-all text-muted-foreground">{finalUrl}</span>}
        </>
      )}
    </span>
  )
}

function VariantTable({ variants }: { variants: GoLiveVariant[] }) {
  return (
    <div className="overflow-x-auto rounded-md border bg-card">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">Variant</th>
            <th className="px-2 py-1.5 text-left font-medium">Redirectketen en eindadres</th>
            <th className="px-2 py-1.5 text-left font-medium">Oordeel</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {variants.map((v) => (
            <tr key={v.start} className="align-top">
              <td className="whitespace-nowrap px-2 py-1.5 font-medium">{v.start}</td>
              <td className="px-2 py-1.5">
                <Chain chain={v.chain} finalUrl={v.final_url} finalStatus={v.final_status} error={v.error} />
              </td>
              <td className="px-2 py-1.5">
                <div className="flex flex-col items-start gap-1">
                  <AutoStatusBadge status={v.status} />
                  <span className="text-muted-foreground">{v.note}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function UrlRows({ title, rows, total, render }: {
  title: string
  rows: GoLiveUrlRow[] | undefined
  total: number | undefined
  render: (row: GoLiveUrlRow) => React.ReactNode
}) {
  if (!rows?.length) return null
  return (
    <div>
      <Heading>
        {title} ({total ?? rows.length})
      </Heading>
      <RowList>
        {rows.slice(0, MAX_ROWS).map((row, index) => (
          <li key={`${row.page}-${row.url}-${index}`} className="space-y-0.5 px-2 py-1.5">
            <p className="text-muted-foreground">
              Op <UrlLink url={row.page} label={row.page === "sitemap" ? "de sitemap" : pathOf(row.page)} />
            </p>
            <div className="flex min-w-0 flex-wrap items-center gap-2">{render(row)}</div>
          </li>
        ))}
      </RowList>
      <More total={total} shown={Math.min(rows.length, MAX_ROWS)} />
    </div>
  )
}

function SimpleList({ title, items, total }: {
  title: string
  items: { key: string; content: React.ReactNode }[]
  total?: number
}) {
  if (!items.length) return null
  return (
    <div>
      <Heading>
        {title} ({total ?? items.length})
      </Heading>
      <RowList>
        {items.slice(0, MAX_ROWS).map((item) => (
          <li key={item.key} className="flex min-w-0 flex-wrap items-center gap-2 px-2 py-1.5">
            {item.content}
          </li>
        ))}
      </RowList>
      <More total={total} shown={Math.min(items.length, MAX_ROWS)} />
    </div>
  )
}

function Wrap({ children }: { children: React.ReactNode }) {
  return <div className="space-y-3 text-xs">{children}</div>
}

/**
 * Detailweergave van een livegangpunt in de checklist; null = de standaard evidence-lijst.
 * Een gewone functie en geen component: alleen een echte null laat de checklist terugvallen op de evidence.
 */
export function goLiveItemDetails(item: ChecklistItem): React.ReactNode {
  const d = item.auto?.details as GoLiveDetails | null | undefined
  if (!d || typeof d !== "object") return null

  switch (item.key) {
    case "gl_https": {
      if (!d.variant) return null
      const v = d.variant
      return (
        <Wrap>
          <VariantTable variants={[{ ...v, status: item.auto?.status ?? "unknown", note: item.auto?.message ?? "" }]} />
          <p className="text-muted-foreground">
            HSTS: {d.hsts ? <code className="rounded bg-muted px-1">{d.hsts}</code> : "geen header (alleen ter informatie)"}
          </p>
        </Wrap>
      )
    }
    case "gl_http_redirect":
    case "gl_host_variants":
      return d.variants?.length ? (
        <Wrap>
          <VariantTable variants={d.variants} />
          {d.target && <p className="text-muted-foreground">Voorkeursadres: {d.target}</p>}
        </Wrap>
      ) : null

    case "gl_mixed_content": {
      if (!d.active?.length && !d.passive?.length) return null
      const resource = (row: GoLiveUrlRow) => (
        <>
          <Pill>{`<${row.tag}>`}</Pill>
          <UrlLink url={row.url} />
        </>
      )
      return (
        <Wrap>
          <UrlRows title="Actief (wordt geblokkeerd)" rows={d.active} total={d.active_total} render={resource} />
          <UrlRows title="Passief (waarschuwing in de browser)" rows={d.passive} total={d.passive_total} render={resource} />
        </Wrap>
      )
    }

    case "gl_internal_urls": {
      const rows = Array.isArray(d.urls) ? d.urls : []
      if (!rows.length) return null
      return (
        <Wrap>
          <UrlRows
            title="Interne URL's naar een verkeerd adres"
            rows={rows}
            total={d.total}
            render={(row) => (
              <>
                <Pill>{row.kind}</Pill>
                <Pill tone="amber">{ISSUE_LABELS[row.issue ?? ""] ?? row.issue}</Pill>
                <UrlLink url={row.url} />
              </>
            )}
          />
        </Wrap>
      )
    }

    case "gl_staging_refs":
    case "gl_staging_shielded": {
      if (!d.hosts?.length) return null
      return (
        <Wrap>
          <SimpleList
            title="Testadressen"
            items={d.hosts.map((h) => ({
              key: h.host,
              content: (
                <>
                  <Pill tone={h.level === "error" ? "red" : "amber"}>{h.level === "error" ? "Test" : "Mogelijk test"}</Pill>
                  <span className="font-medium">{h.host}</span>
                  <span className="text-muted-foreground">
                    {h.reason} · {h.pages} pagina(&apos;s) · {h.types.map((t) => REF_TYPE_LABELS[t] ?? t).join(", ")}
                  </span>
                </>
              ),
            }))}
          />
          {item.key === "gl_staging_refs" && (
            <UrlRows
              title="Verwijzingen"
              rows={d.refs}
              total={d.total}
              render={(row) => (
                <>
                  <Pill>{REF_TYPE_LABELS[row.type ?? ""] ?? row.type}</Pill>
                  <UrlLink url={row.url} />
                </>
              )}
            />
          )}
        </Wrap>
      )
    }

    case "gl_robots_open":
      return d.blocked?.length ? (
        <Wrap>
          <SimpleList
            title="Geblokkeerd voor Googlebot"
            total={d.blocked_total}
            items={d.blocked.map((b) => ({
              key: b.url,
              content: (
                <>
                  <UrlLink url={b.url} label={pathOf(b.url)} />
                  {b.rule && <code className="rounded bg-muted px-1 text-muted-foreground">{b.rule}</code>}
                </>
              ),
            }))}
          />
        </Wrap>
      ) : null

    case "gl_noindex":
      return d.pages?.length ? (
        <Wrap>
          <SimpleList
            title="Pagina's met noindex"
            total={d.total}
            items={d.pages.map((p) => ({
              key: p.url,
              content: (
                <>
                  <UrlLink url={p.url} label={pathOf(p.url)} />
                  <span className="text-muted-foreground">{p.reason}</span>
                  {p.in_sitemap && <Pill tone="amber">In sitemap</Pill>}
                </>
              ),
            }))}
          />
        </Wrap>
      ) : null

    case "gl_sitemap": {
      const lists = [
        { title: "URL's op een ander domein", urls: d.foreign ?? [], total: d.foreign_total },
        { title: "URL's via http:// of op een andere host", urls: d.wrong_host ?? [], total: d.wrong_host_total },
      ]
      const hasAny = lists.some((l) => l.urls.length) || (d.not_ok?.length ?? 0) > 0
      if (!hasAny) return null
      return (
        <Wrap>
          {lists.map((l) => (
            <SimpleList
              key={l.title}
              title={l.title}
              total={l.total}
              items={l.urls.map((url) => ({ key: url, content: <UrlLink url={url} /> }))}
            />
          ))}
          <SimpleList
            title="Sitemap-URL's die geen 200 geven"
            total={d.not_ok_total}
            items={(d.not_ok ?? []).map((row) => ({
              key: row.url,
              content: (
                <>
                  <HttpStatusBadge status={row.status} error={row.error} />
                  <UrlLink url={row.url} label={pathOf(row.url)} />
                  {row.error && <span className="text-muted-foreground">{row.error}</span>}
                </>
              ),
            }))}
          />
        </Wrap>
      )
    }

    case "gl_pages_ok":
      if (!d.failing?.length && !d.broken?.length) return null
      return (
        <Wrap>
          <SimpleList
            title="Pagina's met een fout"
            total={d.failing_total}
            items={(d.failing ?? []).map((row) => ({
              key: row.url,
              content: (
                <>
                  <HttpStatusBadge status={row.status} error={row.error} />
                  <UrlLink url={row.url} label={pathOf(row.url)} />
                  {row.error && <span className="text-muted-foreground">{row.error}</span>}
                </>
              ),
            }))}
          />
          <SimpleList
            title="Kapotte interne links"
            total={d.broken_total}
            items={(d.broken ?? []).map((row, index) => ({
              key: `${row.page}-${row.url}-${index}`,
              content: (
                <>
                  <HttpStatusBadge status={row.status} error={row.status === null ? "niet bereikbaar" : null} />
                  <UrlLink url={row.url} label={pathOf(row.url)} />
                  <span className="text-muted-foreground">
                    op <UrlLink url={row.page} label={pathOf(row.page)} />
                  </span>
                </>
              ),
            }))}
          />
        </Wrap>
      )

    case "gl_tracking_installed": {
      const ids = d.ids ?? []
      const missing = (d.missing ?? []).filter((m): m is string => typeof m === "string")
      if (!ids.length && !missing.length && !d.ua?.length && !d.other?.length) return null
      return (
        <Wrap>
          <SimpleList
            title="Tracking-ID's in de HTML"
            items={ids.map((i) => ({
              key: i.id,
              content: (
                <>
                  <Pill tone="blue">{i.kind === "gtm" ? "Tag Manager" : "GA4"}</Pill>
                  <span className="font-medium">{i.id}</span>
                  <span className="text-muted-foreground">
                    op {i.pages} van {d.pages_checked} pagina&apos;s
                  </span>
                </>
              ),
            }))}
          />
          {d.ua && d.ua.length > 0 && (
            <p className="text-muted-foreground">Verouderde Universal Analytics: {d.ua.join(", ")}</p>
          )}
          {d.other && d.other.length > 0 && <p className="text-muted-foreground">Ook gevonden: {d.other.join(", ")}</p>}
          <SimpleList
            title="Pagina's zonder GTM- of GA4-code"
            total={d.missing_total}
            items={missing.map((url) => ({ key: url, content: <UrlLink url={url} label={pathOf(url)} /> }))}
          />
        </Wrap>
      )
    }

    case "gl_viewport": {
      const rows = (d.missing ?? []).filter((m): m is { url: string; viewport: string | null } => typeof m !== "string")
      return rows.length ? (
        <Wrap>
          <SimpleList
            title="Zonder viewport-meta met width=device-width"
            total={d.missing_total}
            items={rows.map((row) => ({
              key: row.url,
              content: (
                <>
                  <UrlLink url={row.url} label={pathOf(row.url)} />
                  {row.viewport && <code className="rounded bg-muted px-1 text-muted-foreground">{row.viewport}</code>}
                </>
              ),
            }))}
          />
        </Wrap>
      ) : null
    }

    case "gl_forms_tested":
      return d.pages?.length ? (
        <Wrap>
          <SimpleList
            title="Pagina's met een formulier"
            total={d.pages_total}
            items={d.pages.map((p) => ({
              key: p.url,
              content: (
                <>
                  <UrlLink url={p.url} label={pathOf(p.url)} />
                  <span className="text-muted-foreground">{p.forms} formulier(en)</span>
                </>
              ),
            }))}
          />
        </Wrap>
      ) : null

    case "gl_404":
      return d.probes?.length ? (
        <Wrap>
          <VariantTable
            variants={d.probes.map((p) => ({
              start: pathOf(p.url),
              status: p.status,
              note: p.note,
              chain: p.chain,
              final_url: p.final_url,
              final_status: p.final_status,
              error: null,
            }))}
          />
        </Wrap>
      ) : null

    case "gl_favicon":
      return d.candidates?.length ? (
        <Wrap>
          <SimpleList
            title="Gecontroleerde favicons"
            items={d.candidates.map((c) => ({
              key: c.url,
              content: (
                <>
                  <Pill tone={c.ok ? "green" : "amber"}>{c.ok ? "Afbeelding" : "Geen afbeelding"}</Pill>
                  <HttpStatusBadge status={c.status} error={c.error} />
                  <UrlLink url={c.url} label={pathOf(c.url)} />
                  {c.content_type && <span className="text-muted-foreground">{c.content_type}</span>}
                  {c.error && <span className="text-muted-foreground">{c.error}</span>}
                </>
              ),
            }))}
          />
        </Wrap>
      ) : null

    default:
      return null
  }
}
