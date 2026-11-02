import React, { createContext, useContext, useState, useEffect } from 'react'
import { User, Organisation } from '../types'
import { api } from '../api'

interface AuthContextType {
  user: User | null
  currentOrg: Organisation | null
  loading: boolean
  login: (email: string, pass: string, orgId?: string) => Promise<void>
  register: (email: string, pass: string, name: string, orgId: string) => Promise<void>
  logout: () => void
  setOrganisation: (org: Organisation) => void
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [currentOrg, setCurrentOrg] = useState<Organisation | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    initAuth()
  }, [])

  const initAuth = async () => {
    try {
      const token = localStorage.getItem('auth_token')
      if (token) {
        const u = await api.getMe()
        setUser(u)
        const org = await api.getOrganisation(u.org_id)
        setCurrentOrg(org)
      } else {
        // Default to himali-tea if no session
        const org = await api.getOrganisation('himali-tea').catch(() => null)
        if (org) setCurrentOrg(org)
      }
    } catch (err) {
      localStorage.removeItem('auth_token')
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  const login = async (email: string, pass: string, orgId?: string) => {
    const res = await api.login({ email, password: pass, org_id: orgId })
    localStorage.setItem('auth_token', res.access_token)
    setUser(res.user)
    const org = await api.getOrganisation(res.user.org_id)
    setCurrentOrg(org)
  }

  const register = async (email: string, pass: string, name: string, orgId: string) => {
    const res = await api.register({ email, password: pass, name, org_id: orgId })
    localStorage.setItem('auth_token', res.access_token)
    setUser(res.user)
    const org = await api.getOrganisation(res.user.org_id)
    setCurrentOrg(org)
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    setUser(null)
  }

  const setOrganisation = (org: Organisation) => {
    setCurrentOrg(org)
  }

  const refreshMe = async () => {
    try {
      const u = await api.getMe()
      setUser(u)
    } catch {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        currentOrg,
        loading,
        login,
        register,
        logout,
        setOrganisation,
        refreshMe,
      }}
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

