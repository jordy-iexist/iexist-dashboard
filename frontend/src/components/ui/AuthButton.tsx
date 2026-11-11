'use client'

import Link from 'next/link'
import { Button } from './button'
import { type AuthUser } from '@/lib/auth-types'

interface AuthButtonProps {
  user: AuthUser | null
}

export function AuthButton({ user }: AuthButtonProps) {
  if (user) {
    return (
      <Button asChild variant="outline">
        <Link href="/dashboard">Dashboard</Link>
      </Button>
    )
  }

  return (
    <Button asChild>
      <Link href="/login">Inloggen</Link>
    </Button>
  )
}
