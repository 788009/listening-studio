import { apiRequest } from './client'
import type { UserRole } from '@/stores/auth'

export interface ManagedUser {
  userId: string
  username: string | null
  role: UserRole
  createdAt: string
}

export interface ManagedUserPage {
  items: ManagedUser[]
  page: number
  pageSize: number
  total: number
}

export type AssignableUserRole = Extract<UserRole, 'user' | 'admin'>

export function listManagedUsers(page = 1, pageSize = 25): Promise<ManagedUserPage> {
  const query = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  })
  return apiRequest<ManagedUserPage>(`/users?${query.toString()}`)
}

export function updateManagedUserRole(
  userId: string,
  role: AssignableUserRole,
): Promise<ManagedUser> {
  return apiRequest<ManagedUser>(`/users/${encodeURIComponent(userId)}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
}
