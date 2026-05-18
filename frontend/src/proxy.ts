import { NextResponse, type NextRequest } from 'next/server'
import { ACCESS_TOKEN_COOKIE_NAME } from '@/lib/auth-session'

export async function proxy(request: NextRequest) {
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)?.value
  const isAuthenticated = Boolean(accessToken)

  // Redirect authenticated users from home to dashboard
  if (request.nextUrl.pathname === '/' && isAuthenticated) {
    const url = request.nextUrl.clone()
    url.pathname = '/dashboard'
    return Response.redirect(url)
  }

  // Redirect unauthenticated users from protected routes to login
  if (request.nextUrl.pathname.startsWith('/dashboard') && !isAuthenticated) {
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    return Response.redirect(url)
  }

  // Redirect authenticated users from auth pages to dashboard
  if ((request.nextUrl.pathname === '/login' || request.nextUrl.pathname === '/signup') && isAuthenticated) {
    const url = request.nextUrl.clone()
    url.pathname = '/dashboard'
    return Response.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/',
    '/login',
    '/signup',
    '/dashboard/:path*',
  ],
}
