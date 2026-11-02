import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import { Organisation } from '../types'
import { api, extractErrorMessage } from '../api'
import { Bot, Shield, ArrowRight, Sparkles, CheckCircle2 } from 'lucide-react'

interface LoginPageProps {
  onNavigateToSignup: () => void
  currentOrgSlug?: string
  onSwitchOrgSlug: (slug: string) => void
}

export const LoginPage: React.FC<LoginPageProps> = ({
  onNavigateToSignup,
  currentOrgSlug = 'himali-tea',
  onSwitchOrgSlug,
}) => {
  const { login } = useAuth()
  const [organisations, setOrganisations] = useState<Organisation[]>([])
  const [selectedOrg, setSelectedOrg] = useState<Organisation | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('Password123!')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadOrgs()
  }, [])

  useEffect(() => {
    if (organisations.length > 0) {
      const match = organisations.find((o) => o.slug === currentOrgSlug || o.id === currentOrgSlug) || organisations[0]
      setSelectedOrg(match)
    }
  }, [currentOrgSlug, organisations])

  const loadOrgs = async () => {
    try {
      const orgs = await api.getOrganisations()
      setOrganisations(orgs)
      const match = orgs.find((o) => o.slug === currentOrgSlug) || orgs[0]
      setSelectedOrg(match)
    } catch (err) {
      console.error(err)
    }
  }

  const handleSelectOrg = (org: Organisation) => {
    setSelectedOrg(org)
    onSwitchOrgSlug(org.slug)
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedOrg) return
    setLoading(true)
    setError(null)
    try {
      await login(email, password, selectedOrg.id)
    } catch (err: any) {
      setError(extractErrorMessage(err, 'Authentication failed. Please verify credentials.'))
    } finally {
      setLoading(false)
    }
  }

  const handleQuickLogin = async (testEmail: string) => {
    if (!selectedOrg) return
    setEmail(testEmail)
    setPassword('Password123!')
    setLoading(true)
    setError(null)
    try {
      await login(testEmail, 'Password123!', selectedOrg.id)
    } catch (err: any) {
      setError(extractErrorMessage(err, 'Authentication failed. Please verify credentials.'))
    } finally {
      setLoading(false)
    }
  }

  if (!selectedOrg) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 text-sm">
        Loading organization entry point...
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-8 relative overflow-hidden">
      {/* Background Decorative Glow */}
      <div
        className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full blur-3xl opacity-20 pointer-events-none"
        style={{ backgroundColor: selectedOrg.primary_color }}
      />

      <div className="sm:mx-auto sm:w-full sm:max-w-md relative z-10">
        {/* Entry Point Selector Tabs */}
        <div className="flex p-1 rounded-2xl bg-slate-900 border border-slate-800 mb-6">
          {organisations.map((org) => {
            const isSelected = org.id === selectedOrg.id
            return (
              <button
                key={org.id}
                onClick={() => handleSelectOrg(org)}
                className={`flex-1 py-2 px-3 rounded-xl text-xs font-semibold transition ${
                  isSelected
                    ? 'bg-slate-800 text-white shadow-md border border-slate-700/60'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {org.name}
              </button>
            )
          })}
        </div>

        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div
            className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center text-white shadow-xl font-bold text-xl"
            style={{
              background: `linear-gradient(135deg, ${selectedOrg.primary_color}, ${selectedOrg.secondary_color})`,
              boxShadow: `0 8px 24px ${selectedOrg.primary_color}50`,
            }}
          >
            {selectedOrg.name.charAt(0)}
          </div>
          <h2 className="text-2xl font-bold text-white tracking-tight">{selectedOrg.name}</h2>
          <p className="text-xs text-slate-300 max-w-sm mx-auto leading-relaxed">
            {selectedOrg.id === 'org_a' || selectedOrg.slug === 'himali-tea'
              ? "Hello! I'm your tea assistant. Sign in to track orders or discover new blends."
              : "Namaste! I'm your wellness assistant. Sign in to book or manage your appointments."}
          </p>
        </div>

        {/* Form Card */}
        <div className="mt-8 bg-slate-900/90 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-md">
          {error && (
            <div className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs leading-relaxed">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Email Address</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@domain.com"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-xs sm:text-sm placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-xs sm:text-sm placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 rounded-xl text-xs sm:text-sm font-semibold text-white shadow-lg transition active:scale-98 flex items-center justify-center gap-2 mt-2"
              style={{
                backgroundColor: selectedOrg.primary_color,
                boxShadow: `0 4px 14px ${selectedOrg.primary_color}60`,
              }}
            >
              <span>{loading ? 'Authenticating...' : 'Sign In to Agent Portal'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>

          {/* Quick 1-Click Test Logins (Requirement) */}
          <div className="mt-6 pt-5 border-t border-slate-800 text-xs">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-2">
              1-Click Verified Test Logins:
            </span>
            <div className="grid grid-cols-2 gap-2">
              {selectedOrg.id === 'org_a' ? (
                <>
                  <button
                    type="button"
                    onClick={() => handleQuickLogin('aayush@himali.test')}
                    className="p-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-left border border-slate-700 transition active:scale-98"
                  >
                    <div className="font-semibold text-slate-200 truncate">Aayush (Customer)</div>
                    <div className="text-[10px] text-slate-400">aayush@himali.test</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickLogin('admin@himali.test')}
                    className="p-2.5 rounded-xl bg-purple-950/40 hover:bg-purple-900/50 text-left border border-purple-500/30 transition active:scale-98"
                  >
                    <div className="font-semibold text-purple-200 truncate">Himali Admin</div>
                    <div className="text-[10px] text-purple-400">admin@himali.test</div>
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => handleQuickLogin('sita@lotus.test')}
                    className="p-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-left border border-slate-700 transition active:scale-98"
                  >
                    <div className="font-semibold text-slate-200 truncate">Sita (Customer)</div>
                    <div className="text-[10px] text-slate-400">sita@lotus.test</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickLogin('admin@lotus.test')}
                    className="p-2.5 rounded-xl bg-purple-950/40 hover:bg-purple-900/50 text-left border border-purple-500/30 transition active:scale-98"
                  >
                    <div className="font-semibold text-purple-200 truncate">Lotus Admin</div>
                    <div className="text-[10px] text-purple-400">admin@lotus.test</div>
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="mt-5 text-center text-xs text-slate-400">
            Don't have an account?{' '}
            <button
              onClick={onNavigateToSignup}
              className="font-semibold text-emerald-400 hover:text-emerald-300 transition"
            >
              Sign up on this entry point
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

