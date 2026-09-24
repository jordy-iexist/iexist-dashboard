import Image from "next/image"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"

export function KlantHero({
  backHref = "/dashboard/klanten",
  backLabel = "Terug naar klanten",
  eyebrow,
  title,
  children,
}: {
  backHref?: string | null
  backLabel?: string
  eyebrow?: string | null
  title: string
  children?: React.ReactNode
}) {
  return (
    <div className="space-y-3">
      {backHref && (
        <Link
          href={backHref}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {backLabel}
        </Link>
      )}

      <section className="hero-iexist p-6 sm:p-10">
        <Image
          src="/hero-img.png"
          alt=""
          fill
          priority
          sizes="(min-width: 1024px) 1024px, 100vw"
          className="object-cover dark:opacity-15"
        />
        <div className="relative space-y-4">
          <div className="space-y-2">
            {eyebrow && (
              <p className="text-sm font-medium text-muted-foreground">
                {eyebrow}
              </p>
            )}
            <h1 className="text-4xl font-bold leading-tight text-primary sm:text-5xl">
              {title}
            </h1>
          </div>
          {children}
        </div>
      </section>
    </div>
  )
}
