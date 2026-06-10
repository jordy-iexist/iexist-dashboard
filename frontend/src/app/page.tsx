import Image from 'next/image'
import Link from 'next/link'
import { Button } from '@/components/ui/button'

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-16">
      <div className="flex w-full max-w-2xl flex-col items-center">
        <Image
          src="/logo.svg"
          alt="iExist"
          width={1776}
          height={422}
          priority
          className="h-auto w-full max-w-md"
        />

        <div className="mt-12 flex w-full max-w-sm flex-col gap-3 sm:flex-row">
          <Button
            asChild
            size="lg"
            className="h-12 flex-1 bg-brand-blue text-white hover:bg-brand-blue-light focus-visible:ring-brand-blue/40"
          >
            <Link href="/login">Inloggen</Link>
          </Button>
          <Button
            asChild
            size="lg"
            className="h-12 flex-1 bg-brand-yellow font-semibold text-brand-blue hover:bg-brand-yellow/85 focus-visible:ring-brand-yellow/50"
          >
            <Link href="/signup">Registreren</Link>
          </Button>
        </div>
      </div>
    </main>
  )
}
