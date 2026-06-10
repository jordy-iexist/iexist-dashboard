import { NextResponse } from 'next/server'
import { clearAccessTokenCookie, getAccessToken } from '@/lib/auth-session'
import { getBackendApiUrl } from '@/lib/backend-api'

export async function POST() {
  const token = await getAccessToken()
  if (token) {
    try {
      await fetch(`${getBackendApiUrl()}/api/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
    } catch {
      // Backend onbereikbaar: cookie wordt alsnog gewist.
    }
  }

  const response = NextResponse.redirect(
    new URL('/login', process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000')
  )
  clearAccessTokenCookie(response)
  return response
}
