import { Metadata } from 'next'
import Image from 'next/image'
import Link from 'next/link'
import { redirect } from 'next/navigation'
import {
  ArrowRight,
  FileText,
  LayoutTemplate,
  Lightbulb,
  ScanLine,
  Search,
  Settings,
  Sparkles,
  TrendingUp,
  Upload,
  UserPlus,
  Users,
} from 'lucide-react'
import { getCurrentUser } from '@/lib/auth'
import { getDisplayName } from '@/lib/utils'
import { Button } from '@/components/ui/button'

export const metadata: Metadata = {
  title: 'Dashboard',
  description: 'Dashboard overview',
}

const quickLinks = [
  {
    title: 'CSV uploaden',
    url: '/dashboard/blogs/upload',
    icon: Upload,
  },
  {
    title: 'Nieuwe klant',
    url: '/dashboard/klanten/nieuw',
    icon: UserPlus,
  },
  {
    title: 'Keywords checken',
    url: '/dashboard/seo/tracker',
    icon: Search,
  },
  {
    title: 'Instellingen',
    url: '/dashboard/settings',
    icon: Settings,
  },
]

const features = [
  {
    title: 'Blogs',
    description: "Genereer AI-blogs uit een CSV en publiceer ze direct naar WordPress.",
    url: '/dashboard/blogs',
    icon: FileText,
  },
  {
    title: "Landingspagina's",
    description: "Maak landingspagina's op schaal, gevoed door je eigen data.",
    url: '/dashboard/landing-pages',
    icon: LayoutTemplate,
  },
  {
    title: 'Klanten',
    description: 'Beheer klantwebsites, maandelijkse linkdoelen en spreadsheets.',
    url: '/dashboard/klanten',
    icon: Users,
  },
  {
    title: 'SEO Tracker',
    description: 'Volg keyword-posities in Google en zie wat er stijgt of daalt.',
    url: '/dashboard/seo/tracker',
    icon: TrendingUp,
  },
  {
    title: 'Meta Generator',
    description: 'Laat AI pakkende meta titles en descriptions per pagina schrijven.',
    url: '/dashboard/seo/meta-generator',
    icon: Sparkles,
  },
  {
    title: 'Website Audit',
    description: 'Crawl een website en spoor technische SEO-problemen op.',
    url: '/dashboard/audit',
    icon: ScanLine,
  },
]

function getGreeting() {
  const hour = Number(
    new Intl.DateTimeFormat('nl-NL', {
      hour: 'numeric',
      hourCycle: 'h23',
      timeZone: 'Europe/Amsterdam',
    }).format(new Date()),
  )
  if (hour < 12) return 'Goedemorgen'
  if (hour < 18) return 'Goedemiddag'
  return 'Goedenavond'
}

function HeroIllustration() {
  return (
    <div className="relative hidden h-56 w-72 shrink-0 md:block">
      {/* Grafiekkaart */}
      <div className="absolute right-0 top-2 w-60 rounded-xl bg-neutral-900/90 p-4 shadow-xl ring-1 ring-white/10 backdrop-blur-sm">
        <div className="mb-3 flex items-center gap-2">
          <span className="size-2 rounded-full bg-[#fab806]" />
          <span className="h-2 w-20 rounded-full bg-white/30" />
        </div>
        <svg viewBox="0 0 220 90" className="h-24 w-full" aria-hidden="true">
          <defs>
            <linearGradient id="hero-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#fab806" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#fab806" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            d="M0 80 L30 70 L60 74 L90 52 L120 58 L150 34 L180 38 L220 10 L220 90 L0 90 Z"
            fill="url(#hero-area)"
          />
          <path
            d="M0 80 L30 70 L60 74 L90 52 L120 58 L150 34 L180 38 L220 10"
            fill="none"
            stroke="#fab806"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="220" cy="10" r="5" fill="#fab806" />
        </svg>
      </div>

      {/* Zoekbalk */}
      <div className="absolute bottom-4 left-0 flex w-52 items-center gap-2 rounded-full bg-white px-4 py-2.5 shadow-lg">
        <Search className="size-4 text-black" />
        <span className="h-2 w-24 rounded-full bg-slate-200" />
        <span className="ml-auto rounded-full bg-[#fab806] px-2 py-0.5 text-[10px] font-bold text-black">
          #1
        </span>
      </div>

      {/* Logo */}
      <div className="absolute bottom-0 right-4 flex size-16 rotate-6 items-center justify-center rounded-2xl bg-white shadow-xl">
        <Image src="/iExist-favicon-X-blauwgeel.svg" alt="iExist" width={36} height={36} className="size-9" />
      </div>
    </div>
  )
}

export default async function DashboardPage() {
  const user = await getCurrentUser()
  if (!user) {
    redirect('/login')
  }

  const name = user.email ? getDisplayName(user.email) : 'daar'

  return (
    <div className="space-y-8">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-black from-30% via-neutral-800 via-60% to-neutral-500 md:to-white p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 size-64 rounded-full bg-[#fab806]/20 blur-3xl" />

        <div className="relative flex items-center justify-between gap-8">
          <div className="max-w-xl space-y-4">
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
              {getGreeting()}, {name}! 👋
            </h1>
            <p className="text-white/75">
              Klaar om vandaag wat moois te maken? Genereer blogs, check je rankings of laat een
              website auditen — alles begint hier.
            </p>
            <div className="flex flex-wrap gap-3 pt-1">
              <Button asChild variant="secondary" className="border-transparent">
                <Link href="/dashboard/blogs/upload">
                  <Upload />
                  Nieuwe blogs uploaden
                </Link>
              </Button>
            </div>
            <p className="text-xs text-white/50">Ingelogd als {user.email}</p>
          </div>

          <HeroIllustration />
        </div>
      </section>

      {/* Quicklinks */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Snel aan de slag</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {quickLinks.map((item) => (
            <Link
              key={item.url}
              href={item.url}
              className="group flex items-center gap-3 rounded-xl border bg-card p-4 transition hover:border-neutral-400 hover:shadow-sm"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-black dark:bg-white/10 dark:text-white">
                <item.icon className="size-5" />
              </span>
              <span className="text-sm font-medium">{item.title}</span>
              <ArrowRight className="ml-auto size-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-foreground" />
            </Link>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Wat kun je doen?</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature) => (
            <Link
              key={feature.url}
              href={feature.url}
              className="group flex flex-col gap-3 rounded-xl border bg-card p-5 transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <span className="flex size-11 items-center justify-center rounded-xl bg-neutral-100 text-black dark:bg-white/10 dark:text-white">
                <feature.icon className="size-5" />
              </span>
              <div className="space-y-1">
                <h3 className="font-semibold">{feature.title}</h3>
                <p className="text-sm text-muted-foreground">{feature.description}</p>
              </div>
              <span className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-primary dark:text-foreground">
                Openen
                <ArrowRight className="size-4 transition group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* Tip */}
      <div className="flex items-start gap-3 rounded-xl border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-white/5 text-sm">
        <Lightbulb className="mt-0.5 size-5 shrink-0 text-black dark:text-white" />
        <p>
          <span className="font-semibold">Tip:</span> stel eerst je blog- en AI-instellingen in via{' '}
          <Link href="/dashboard/settings" className="font-medium underline underline-offset-4">
            Instellingen
          </Link>{' '}
          voor de beste resultaten.
        </p>
      </div>
    </div>
  )
}
