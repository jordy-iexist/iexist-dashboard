import { SeoMetaOptimizer } from "@/components/seo/SeoMetaOptimizer"

export const metadata = {
  title: "Meta Generator",
}

export default function SeoMetaGeneratorPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Meta Generator</h1>
        <p className="text-muted-foreground">
          Ontdek pagina&apos;s en genereer/review meta title en description per URL.
        </p>
      </div>

      <SeoMetaOptimizer />
    </div>
  )
}
