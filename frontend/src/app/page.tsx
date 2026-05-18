import Link from 'next/link'
import Header from '@/components/layout/Header'
import Footer from '@/components/layout/Footer'
import { Button } from '@/components/ui/button'

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />

      <main className="flex flex-1 flex-col items-center justify-center px-6 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h1 className="text-5xl font-black tracking-tight text-foreground">
            CSV Blog
            <span className="text-[#FAB806]">Generator</span>
          </h1>
          <p className="mt-6 text-lg text-muted-foreground">
            Upload een CSV-bestand en genereer automatisch blogposts met
            AI. Publiceer direct naar WordPress vanuit één dashboard.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Button
              asChild
              size="lg"
              className="bg-[#FAB806] text-[#171d35] hover:bg-[#FAB806]/90 font-semibold"
            >
              <Link href="/signup">Gratis aan de slag</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/login">Inloggen</Link>
            </Button>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}
