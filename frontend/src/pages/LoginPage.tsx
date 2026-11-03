import React, { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { Organisation } from '../types'
import { extractErrorMessage } from '../api'
import { ArrowRight, Bot, Loader2 } from 'lucide-react'

interface LoginPageProps {
  entryOrg: Organisation
  organisations: Organisation[]
  onSwitchEntry: (slug: string) => void
  onNavigateToSignup: () => void
}

/** One-click demo accounts, keyed by entry point. They are the seeded test logins listed in the README. */
const DEMO_LOGINS: Record<string, { label: string; email: string; admin?: boolean }[]> = {
  'himali-tea': [
    { label: 'Aayush (customer)', email: 'aayush@himali.test' },
    { label: 'Himali admin', email: 'admin@himali.test', admin: true },
  ],
  'lotus-wellness': [
    { label: 'Sita (customer)', email: 'sita@lotus.test' },
    { label: 'Lotus admin', email: 'admin@lotus.test', admin: true },
  ],
  'everest-gear': [
    { label: 'Karma (customer)', email: 'climber@everest.test' },
    { label: 'Everest admin', email: 'admin@everest.test', admin: true },
  ],
}

export const LoginPage: React.FC<LoginPageProps> = ({ entryOrg, organisations, onSwitchEntry, onNavigateToSignup }) => {
  const { login, notice, clearNotice } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const demo = DEMO_LOGINS[entryOrg.slug] || []

  const signIn = async (mail: string, pass: string) => {
    setLoading(true)
    setError(null)
    clearNotice()
    try {
      await login(mail, pass, entryOrg.id)
    } catch (err: any) {
      setError(extractErrorMessage(err, 'Sign in failed. Please check your details.'))
      setLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    signIn(email, password)
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-8 px-4 sm:px-6 relative overflow-hidden">
      <div
        className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full blur-3xl opacity-25 pointer-events-none"
        style={{ backgroundColor: entryOrg.primary_color }}
      />

      <div className="mx-auto w-full max-w-md relative z-10">
        {organisations.length > 1 && (
          <nav aria-label="Organisation entry points" className="flex p-1 rounded-2xl bg-slate-900 border border-slate-800 mb-5 gap-1">
            {organisations.map((org) => (
              <button
                key={org.id}
                onClick={() => onSwitchEntry(org.slug)}
                aria-current={org.id === entryOrg.id ? 'page' : undefined}
                className={`flex-1 py-2 px-2 rounded-xl text-[11px] sm:text-xs font-semibold transition truncate ${
                  org.id === entryOrg.id ? 'bg-slate-800 text-white border border-slate-700/60' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {org.name}
              </button>
            ))}
          </nav>
        )}

        <header className="text-center space-y-2">
          <div
            className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center text-white shadow-xl font-bold text-xl"
            style={{
              background: `linear-gradient(135deg, ${entryOrg.primary_color}, ${entryOrg.secondary_color})`,
              boxShadow: `0 8px 24px ${entryOrg.primary_color}50`,
            }}
          >
            {entryOrg.name.charAt(0)}
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">{entryOrg.name}</h1>
          {entryOrg.tagline && <p className="text-xs text-slate-400">{entryOrg.tagline}</p>}
        </header>

        {/* The agent greets the visitor in the organisation's own colours. */}
        <div className="mt-5 flex gap-3 items-start">
          <div
            className="w-9 h-9 rounded-xl shrink-0 flex items-center justify-center text-white"
            style={{ backgroundColor: entryOrg.primary_color }}
            aria-hidden
          >
            <Bot className="w-5 h-5" />
          </div>
          <div className="rounded-2xl rounded-tl-sm border px-4 py-3 text-sm text-slate-200 leading-relaxed bg-slate-900/80"
               style={{ borderColor: `${entryOrg.primary_color}80` }}>
            <div className="text-[11px] font-semibold mb-0.5" style={{ color: entryOrg.accent_color }}>
              {entryOrg.agent_name} <span className="text-slate-500 font-normal">· {entryOrg.agent_role}</span>
            </div>
            {entryOrg.greeting || 'Hello! Sign in to start chatting.'}
          </div>
        </div>

        <div className="mt-6 bg-slate-900/90 border border-slate-800 rounded-2xl p-5 sm:p-7 shadow-2xl backdrop-blur-md">
          {notice && (
            <div role="status" className="mb-4 p-3 rounded-xl bg-amber-950/40 border border-amber-500/30 text-amber-200 text-xs">{notice}</div>
          )}
          {error && (
            <div role="alert" className="mb-4 p-3 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs leading-relaxed">{error}</div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-xs font-medium text-slate-300 mb-1">Email address</label>
              <input
                id="email" type="email" required autoComplete="username" value={email}
                onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-slate-300 mb-1">Password</label>
              <input
                id="password" type="password" required autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm placeholder-slate-500 focus:outline-hidden focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/30 transition"
              />
            </div>
            <button
              type="submit" disabled={loading}
              className="w-full py-3 px-4 rounded-xl text-sm font-semibold text-white shadow-lg transition active:scale-98 flex items-center justify-center gap-2 disabled:opacity-60"
              style={{ backgroundColor: entryOrg.primary_color, boxShadow: `0 4px 14px ${entryOrg.primary_color}60` }}
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              <span>{loading ? 'Signing in...' : `Sign in to ${entryOrg.name}`}</span>
              {!loading && <ArrowRight className="w-4 h-4" />}
            </button>
          </form>

          {demo.length > 0 && (
            <div className="mt-6 pt-5 border-t border-slate-800">
              <span className="text-[11px] font-semibold text-slate-400 block mb-2">
                Test logins <span className="font-normal">(password: <code className="text-slate-300">Password123!</code>)</span>
              </span>
              <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-2">
                {demo.map((d) => (
                  <button
                    key={d.email} type="button" disabled={loading}
                    onClick={() => { setEmail(d.email); setPassword('Password123!'); signIn(d.email, 'Password123!') }}
                    className={`p-2.5 rounded-xl text-left border transition active:scale-98 disabled:opacity-60 ${
                      d.admin ? 'bg-purple-950/40 hover:bg-purple-900/50 border-purple-500/30' : 'bg-slate-800/80 hover:bg-slate-700/80 border-slate-700'
                    }`}
                  >
                    <div className={`text-xs font-semibold truncate ${d.admin ? 'text-purple-200' : 'text-slate-200'}`}>{d.label}</div>
                    <div className="text-[10px] text-slate-400 truncate">{d.email}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <p className="mt-5 text-center text-xs text-slate-400">
            New here?{' '}
            <button onClick={onNavigateToSignup} className="font-semibold hover:underline" style={{ color: entryOrg.accent_color }}>
              Create an account at {entryOrg.name}
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
