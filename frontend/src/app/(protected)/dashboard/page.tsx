import { Metadata } from 'next'
import { redirect } from 'next/navigation'
import { getCurrentUser } from '@/lib/auth'
import { getDisplayName } from '@/lib/utils'

export const metadata: Metadata = {
  title: 'Dashboard',
  description: 'Dashboard overview',
}

export default async function DashboardPage() {
  const user = await getCurrentUser()
  if (!user) {
    redirect('/login')
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
        Welkom terug {user?.email ? getDisplayName(user.email) : 'gebruiker'}! Hier is een overzicht van je account en recente activiteiten.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border bg-card p-6">
          <h3 className="font-semibold mb-2">Account e-mail</h3>
          <p className="text-2xl font-bold">{user?.email}</p>
        </div>

        <div className="rounded-lg border bg-card p-6">
          <h3 className="font-semibold mb-2">Gebruikers id</h3>
          <p className="text-sm font-mono truncate">{user?.id}</p>
        </div>

        <div className="rounded-lg border bg-card p-6">
          <h3 className="font-semibold mb-2">Account aangemaakt</h3>
          <p className="text-sm">
            {user?.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}
          </p>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-6">
        <h2 className="text-xl font-semibold mb-4">Snel overzicht</h2>
        <p className="text-muted-foreground">
        Hier kun je snel belangrijke informatie over je account zien, zoals je e-mail, gebruikers-id en wanneer je account is aangemaakt. Gebruik deze informatie om je account te beheren en bij te houden.
        </p>
      </div>
    </div>
  )
}
