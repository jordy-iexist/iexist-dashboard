export default function Footer() {
  return (
    <footer className="border-t border-border/60 bg-background">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
        <p className="text-sm text-muted-foreground">
          &copy; {new Date().getFullYear()} CSV BlogGenerator
        </p>
        <p className="text-xs text-muted-foreground">
          Powered by GPT-4o-mini &bull; FastAPI &bull; Next.js
        </p>
      </div>
    </footer>
  )
}
