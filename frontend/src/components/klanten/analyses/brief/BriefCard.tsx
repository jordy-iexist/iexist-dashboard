import Link from "next/link"

import { formatInt, ResultCard } from "@/components/klanten/analyses/result-parts"
import { customerHref } from "@/lib/active-customer"
import type { Brief, FormOfAddress, HeadingLevel } from "@/lib/content-brief"
import { cn } from "@/lib/utils"

const FORM_OF_ADDRESS_LABELS: Record<FormOfAddress, string> = {
  je: "je-vorm",
  u: "u-vorm",
}

const HEADING_LABELS: Record<HeadingLevel, string> = {
  h1: "H1",
  h2: "H2",
  h3: "H3",
}

/** Accentkleur van de opsommingstekens, zoals de blauwe pillen in de analyse. */
const ACCENT = "text-blue-600 dark:text-blue-400"

function Block({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  const labelId = `brief-${id}-label`
  return (
    <div role="group" aria-labelledby={labelId} className="space-y-2 border-t pt-4">
      <h3 id={labelId} className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {label}
      </h3>
      {children}
    </div>
  )
}

function Bullets({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="space-y-1.5 text-[13px] leading-5">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2">
          <span aria-hidden="true" className={cn("shrink-0", ACCENT)}>
            •
          </span>
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  )
}

/** De linkerkaart: content brief, alleen-lezen (Figma 04, node 1:182). */
export function BriefCard({ brief, customerId }: { brief: Brief; customerId: string }) {
  const lengthLine = [
    `± ${formatInt(brief.word_count)} woorden`,
    brief.form_of_address ? FORM_OF_ADDRESS_LABELS[brief.form_of_address] : null,
  ]
    .filter(Boolean)
    .join(" · ")

  const profileLink = (
    <Link
      href={customerHref("profiel", customerId)}
      className="underline underline-offset-2 hover:text-foreground"
    >
      klantprofiel
    </Link>
  )

  const conditions: React.ReactNode[] = [
    brief.form_of_address ? (
      lengthLine
    ) : (
      <>
        {lengthLine} · <span className="text-muted-foreground">aanspreekvorm niet vastgelegd ({profileLink})</span>
      </>
    ),
    brief.tone_of_voice?.trim() ? (
      <>Tone of voice: {brief.tone_of_voice.trim()}</>
    ) : (
      <>
        Tone of voice: <span className="text-muted-foreground">niet ingevuld ({profileLink})</span>
      </>
    ),
    brief.internal_links.length > 0 ? (
      <>Interne links: {brief.internal_links.join(", ")}</>
    ) : (
      <>
        Interne links: <span className="text-muted-foreground">geen voorgesteld</span>
      </>
    ),
  ]
  if (brief.schema_types.length > 0) conditions.push(<>Schema: {brief.schema_types.join(" + ")}</>)

  return (
    <ResultCard id="content-brief" title="Content brief" description="Automatisch opgesteld uit de concurrentieanalyse.">
      <Block id="goal" label="Doel & intentie">
        <Bullets items={brief.goal_intent} />
      </Block>

      <Block id="title-meta" label="Title & meta">
        <div className="space-y-1 rounded-lg bg-muted px-3 py-2.5">
          <p className="text-sm leading-5 font-semibold break-words text-[#1a0dab] dark:text-[#8ab4f8]">{brief.title}</p>
          <p className="text-xs leading-[18px] break-words text-muted-foreground">{brief.meta_description}</p>
        </div>
      </Block>

      <Block id="outline" label="Aanbevolen structuur">
        <ol className="space-y-1.5 text-[13px] leading-5">
          {brief.outline.map((item, index) => (
            <li key={index} className={cn("flex gap-2", item.level === "h3" && "pl-4")}>
              <span aria-hidden="true" className={cn("shrink-0", ACCENT)}>
                ›
              </span>
              <span className="w-6 shrink-0 text-xs leading-5 font-medium text-muted-foreground">
                {HEADING_LABELS[item.level]}
              </span>
              <span className="min-w-0 break-words">{item.text}</span>
            </li>
          ))}
        </ol>
      </Block>

      <Block id="conditions" label="Randvoorwaarden">
        <Bullets items={conditions} />
      </Block>
    </ResultCard>
  )
}
