import {
  FileText,
  Globe,
  KeyRound,
  LayoutTemplate,
  type LucideIcon,
  User,
} from "lucide-react"

export type SettingsNavItem = {
  title: string
  description: string
  href: string
  icon: LucideIcon
}

export type SettingsNavGroup = {
  title: string
  items: SettingsNavItem[]
}

export const settingsNavGroups: SettingsNavGroup[] = [
  {
    title: "Account",
    items: [
      {
        title: "Profiel",
        description: "E-mailadres en gebruikers id",
        href: "/dashboard/settings/account",
        icon: User,
      },
      {
        title: "OpenAI API key",
        description: "Persoonlijke key voor blog- en SEO-functies",
        href: "/dashboard/settings/openai",
        icon: KeyRound,
      },
    ],
  },
  {
    title: "Integraties",
    items: [
      {
        title: "WordPress sites",
        description: "Sites waar blogs naartoe gepubliceerd worden",
        href: "/dashboard/settings/wordpress",
        icon: Globe,
      },
    ],
  },
  {
    title: "Content generatie",
    items: [
      {
        title: "Blogs",
        description: "Prompt, model en afbeeldingsgeneratie voor blogs",
        href: "/dashboard/settings/blogs",
        icon: FileText,
      },
      {
        title: "Landingspagina's",
        description: "Prompt en model voor landingspagina's",
        href: "/dashboard/settings/landing-pages",
        icon: LayoutTemplate,
      },
    ],
  },
]
