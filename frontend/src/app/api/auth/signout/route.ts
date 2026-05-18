import { NextResponse } from 'next/server'
import { clearAccessTokenCookie } from '@/lib/auth-session'

export async function POST() {
  const response = NextResponse.redirect(
    new URL('/login', process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000')
  )
  clearAccessTokenCookie(response)
  return response
}
