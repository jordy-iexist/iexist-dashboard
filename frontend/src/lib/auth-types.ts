export type AuthUser = {
  id: string
  email: string
  created_at?: string | null
}

export type AuthResponse = {
  access_token: string
  token_type: "bearer"
  user: AuthUser
}

export type AuthTokenResponse = AuthResponse
