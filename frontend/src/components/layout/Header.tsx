import Link from 'next/link'
import { Button } from '@/components/ui/button'

export default function Header() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
        <Link href="/" className="text-xl font-black text-foreground">
          CSV Blog<span className="text-[#FAB806]">Generator</span>
        </Link>

        <nav className="flex items-center gap-2">
          <Button variant="outline" asChild>
            <Link href="/signup">Aanmelden</Link>
          </Button>
          <Button
            asChild
            className="bg-[#FAB806] text-[#171d35] hover:bg-[#FAB806]/90 font-semibold"
          >
            <Link href="/login">Inloggen</Link>
          </Button>
        </nav>
      </div>
    </header>
  )
}
