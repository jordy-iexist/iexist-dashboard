import Image from "next/image";
import Link from "next/link";
import { Button } from "@/components/ui/button";

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
          className="h-auto w-full max-w-2xs"
        />

        <div className="mt-12 flex w-full max-w-sm flex-col gap-3">
          <Button
            asChild
            size="lg"
            className="py-2 flex-1 bg-brand-yellow text-black hover:bg-brand-yellow/70 focus-visible:ring-brand-blue/40"
          >
            <Link href="/login">Inloggen</Link>
          </Button>
        </div>
      </div>
    </main>
  );
}
