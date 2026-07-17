import { applicationRequest } from './client'


export type LoginMethod = 'none' | 'debug' | 'redirect'

export interface AuthenticationCapabilities {
  loginMethod: LoginMethod
  loginUrl: string | null
}

export interface DebugSessionInput {
  issuer: string
  subject: string
}

export interface EndSessionResult {
  redirectUrl: string | null
}

export async function getAuthenticationCapabilities(): Promise<AuthenticationCapabilities> {
  return applicationRequest<AuthenticationCapabilities>('/auth/capabilities')
}

export async function createDebugSession(input: DebugSessionInput): Promise<void> {
  return applicationRequest<void>('/auth/debug/session', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function endSession(): Promise<EndSessionResult> {
  return applicationRequest<EndSessionResult>('/auth/session', {
    method: 'DELETE',
  })
}
