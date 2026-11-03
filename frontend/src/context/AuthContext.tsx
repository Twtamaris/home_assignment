import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { User, Organisation } from '../types'
import { api, getToken, setToken } from '../api'

interface AuthContextType {
  user: User | null
  /** The organisation the signed-in user belongs to. Null while signed out. */
  currentOrg: Organisation | null
  loading: boolean
  /** Set when a session ended on its own (expired, or signed out from another tab). */
  notice: string | null
  login: (email: string, pass: string, orgId: string) => Promise<void>
  register: (email: string, pass: string, name: string, orgId: string) => Promise<void>
  logout: () => Promise<void>
  clearNotice: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [currentOrg, setCurrentOrg] = useState<Organisation | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<string | null>(null)

  const adopt = useCallback(async (u: User) => {
    const org = await api.getOrganisation(u.org_id)
    setUser(u)
    setCurrentOrg(org)
  }, [])

  // Restore a session from a stored token, if there is one and it is still valid.
  useEffect(() => {
    const restore = async () => {
      try {
        if (getToken()) await adopt(await api.getMe())
      } catch {
        setToken(null)
        setUser(null)
        setCurrentOrg(null)
      } finally {
        setLoading(false)
      }
    }
    restore()
  }, [adopt])

  // api.ts raises this when a call that carried a token came back 401.
  useEffect(() => {
    const onExpired = () => {
      setUser(null)
      setCurrentOrg(null)
      setNotice('Your session has ended. Please sign in again.')
    }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  const login = async (email: string, pass: string, orgId: string) => {
    const res = await api.login({ email, password: pass, org_id: orgId })
    setToken(res.access_token)
    setNotice(null)
    await adopt(res.user)
  }

  const register = async (email: string, pass: string, name: string, orgId: string) => {
    const res = await api.register({ email, password: pass, name, org_id: orgId })
    setToken(res.access_token)
    setNotice(null)
    await adopt(res.user)
  }

  const logout = async () => {
    await api.logout()
    setUser(null)
    setCurrentOrg(null)
    setNotice(null)
  }

  return (
    <AuthContext.Provider
      value={{ user, currentOrg, loading, notice, login, register, logout, clearNotice: () => setNotice(null) }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
