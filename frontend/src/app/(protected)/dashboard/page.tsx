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
        <p className="text-muted-foreground">
          Account e-mail: {user?.email}
        </p>
      </div>
    </div>
  )
}
