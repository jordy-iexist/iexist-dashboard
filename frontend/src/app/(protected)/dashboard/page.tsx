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
import { cn, getDisplayName } from '@/lib/utils'
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
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
  },
  {
    title: 'Nieuwe klant',
    url: '/dashboard/klanten/nieuw',
    icon: UserPlus,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-400',
  },
  {
    title: 'Keywords checken',
    url: '/dashboard/seo/tracker',
    icon: Search,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400',
  },
  {
    title: 'Instellingen',
    url: '/dashboard/settings',
    icon: Settings,
    color: 'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-400',
  },
]

const features = [
  {
    title: 'Blogs',
    description: "Genereer AI-blogs uit een CSV en publiceer ze direct naar WordPress.",
    url: '/dashboard/blogs',
    icon: FileText,
    color: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
  },
  {
    title: "Landingspagina's",
    description: "Maak landingspagina's op schaal, gevoed door je eigen data.",
    url: '/dashboard/landing-pages',
    icon: LayoutTemplate,
    color: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-400',
  },
  {
    title: 'Klanten',
    description: 'Beheer klantwebsites, maandelijkse linkdoelen en spreadsheets.',
    url: '/dashboard/klanten',
    icon: Users,
    color: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-400',
  },
  {
    title: 'SEO Tracker',
    description: 'Volg keyword-posities in Google en zie wat er stijgt of daalt.',
    url: '/dashboard/seo/tracker',
    icon: TrendingUp,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400',
  },
  {
    title: 'Meta Generator',
    description: 'Laat AI pakkende meta titles en descriptions per pagina schrijven.',
    url: '/dashboard/seo/meta-generator',
    icon: Sparkles,
    color: 'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-400',
  },
  {
    title: 'Website Audit',
    description: 'Crawl een website en spoor technische SEO-problemen op.',
    url: '/dashboard/audit',
    icon: ScanLine,
    color: 'bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-400',
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
      <div className="absolute right-0 top-2 w-60 rounded-xl bg-white/10 p-4 ring-1 ring-white/15 backdrop-blur-sm">
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
        <Search className="size-4 text-[#161D35]" />
        <span className="h-2 w-24 rounded-full bg-slate-200" />
        <span className="ml-auto rounded-full bg-[#fab806] px-2 py-0.5 text-[10px] font-bold text-[#161D35]">
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
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#161D35] via-[#1e2850] to-[#2a3566] p-6 text-white shadow-lg sm:p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 size-64 rounded-full bg-[#fab806]/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 left-1/3 size-56 rounded-full bg-sky-400/10 blur-3xl" />

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
              <Button asChild className="bg-[#fab806] text-[#161D35] hover:bg-[#fab806]/90">
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
              className="group flex items-center gap-3 rounded-xl border bg-card p-4 transition hover:border-[#fab806]/60 hover:shadow-sm"
            >
              <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-full', item.color)}>
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
              <span className={cn('flex size-11 items-center justify-center rounded-xl', feature.color)}>
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
      <div className="flex items-start gap-3 rounded-xl border border-[#fab806]/40 bg-[#fab806]/10 p-4 text-sm">
        <Lightbulb className="mt-0.5 size-5 shrink-0 text-[#d99e00]" />
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
