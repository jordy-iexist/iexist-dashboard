import Link from "next/link"

export const metadata = {
  title: "SEO Tools",
}

const tools = [
  {
    title: "SEO Tracker",
    description:
      "Voeg websites en keywords toe en draai SERP scans om rankingposities te volgen.",
    href: "/dashboard/seo/tracker",
    cta: "Open SEO Tracker",
  },
  {
    title: "Meta Generator",
    description:
      "Ontdek pagina's van een website en genereer voorstellen voor meta title en description.",
    href: "/dashboard/seo/meta-generator",
    cta: "Open Meta Generator",
  },
]

export default function SeoToolsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">SEO Tools</h1>
        <p className="text-muted-foreground">
          Kies een tool en ga direct door naar de bijbehorende SEO workflow.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {tools.map((tool) => (
          <Link
            key={tool.title}
            href={tool.href}
            className="rounded-lg border p-5 transition-colors hover:bg-muted/30"
          >
            <h2 className="text-lg font-semibold">{tool.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {tool.description}
            </p>
            <p className="mt-4 text-sm font-medium">{tool.cta}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
