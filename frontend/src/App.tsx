import React, { useState, useEffect, useCallback } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { ChatPage } from './pages/ChatPage'
import { Organisation } from './types'
import { api } from './api'

/** An organisation's entry point is /a/<slug>. Anything else falls back to the first organisation. */
function slugFromPath(): string | null {
  const match = window.location.pathname.match(/^\/a\/([a-zA-Z0-9_-]+)/)
  return match ? match[1] : null
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-300 p-6 text-center">
      {children}
    </div>
  )
}

function AppContent() {
  const { user, currentOrg, loading, logout } = useAuth()
  const [page, setPage] = useState<'login' | 'signup'>('login')
  const [requestedSlug, setRequestedSlug] = useState<string | null>(slugFromPath())
  const [organisations, setOrganisations] = useState<Organisation[]>([])
  const [orgsError, setOrgsError] = useState<string | null>(null)

  const loadOrganisations = useCallback(() => {
    setOrgsError(null)
    api.getOrganisations().then(setOrganisations).catch((e) => setOrgsError(e.message || 'Could not reach the server'))
  }, [])

  useEffect(loadOrganisations, [loadOrganisations])

  // Back and forward between entry points.
  useEffect(() => {
    const onPop = () => setRequestedSlug(slugFromPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // The entry point the visitor is on. It is the organisation login and sign-up are bound to.
  const entryOrg = organisations.find((o) => o.slug === requestedSlug) || (requestedSlug ? null : organisations[0] || null)

  const goToEntry = (slug: string) => {
    window.history.pushState({}, '', `/a/${slug}`)
    setRequestedSlug(slug)
    setPage('login')
  }

  // Whenever the signed-in state changes (sign-in, sign-out, expired session) go back to the sign-in form.
  useEffect(() => {
    setPage('login')
  }, [user])

  // Keep the address bar on the user's own organisation after sign-in.
  useEffect(() => {
    if (user && currentOrg && !requestedSlug) window.history.replaceState({}, '', `/a/${currentOrg.slug}`)
  }, [user, currentOrg, requestedSlug])

  useEffect(() => {
    const org = currentOrg || entryOrg
    document.title = org ? `${org.name} | ${org.agent_name}` : 'Agent platform'
  }, [currentOrg, entryOrg])

  if (loading) {
    return (
      <Centered>
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-xs text-slate-400" role="status">Restoring your session...</span>
      </Centered>
    )
  }

  // Tenant boundary guard: a signed-in user who opens another organisation's address sees a block, not that tenant.
  if (user && currentOrg && requestedSlug && requestedSlug !== currentOrg.slug) {
    return (
      <Centered>
        <div className="max-w-md w-full bg-slate-900 border border-red-500/30 rounded-2xl p-8 shadow-2xl space-y-4">
          <div className="w-12 h-12 bg-red-500/10 text-red-400 rounded-full flex items-center justify-center mx-auto text-xl font-bold">!</div>
          <h2 className="text-xl font-bold text-white">Cross-Tenant Access Blocked</h2>
          <p className="text-sm text-slate-400">
            You are signed in to <strong className="text-emerald-400">{currentOrg.name}</strong>. Your account cannot open{' '}
            <strong className="text-red-400">/a/{requestedSlug}</strong>. The server enforces this on every request too.
          </p>
          <div className="pt-2 space-y-2">
            <button
              onClick={() => window.location.replace(`/a/${currentOrg.slug}`)}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-xl text-sm transition-colors"
            >
              Return to {currentOrg.name}
            </button>
            <button
              onClick={() => logout().then(() => window.location.replace(`/a/${requestedSlug}`))}
              className="w-full py-2.5 px-4 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-sm transition-colors"
            >
              Sign out and use another account
            </button>
          </div>
        </div>
      </Centered>
    )
  }

  if (user && currentOrg) return <ChatPage user={user} org={currentOrg} />

  if (orgsError) {
    return (
      <Centered>
        <p className="text-sm text-rose-300 mb-3" role="alert">{orgsError}</p>
        <button onClick={loadOrganisations} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm text-white">
          Try again
        </button>
      </Centered>
    )
  }

  if (requestedSlug && organisations.length > 0 && !entryOrg) {
    return (
      <Centered>
        <h2 className="text-lg font-bold text-white mb-2">No organisation at /a/{requestedSlug}</h2>
        <div className="flex flex-wrap gap-2 justify-center">
          {organisations.map((o) => (
            <button key={o.id} onClick={() => goToEntry(o.slug)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm text-white">
              {o.name}
            </button>
          ))}
        </div>
      </Centered>
    )
  }

  if (!entryOrg) {
    return (
      <Centered>
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3" />
        <span className="text-xs text-slate-400" role="status">Loading entry point...</span>
      </Centered>
    )
  }

  if (page === 'signup') {
    return <SignupPage entryOrg={entryOrg} onNavigateToLogin={() => setPage('login')} />
  }

  return (
    <LoginPage
      entryOrg={entryOrg}
      organisations={organisations}
      onSwitchEntry={goToEntry}
      onNavigateToSignup={() => setPage('signup')}
    />
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
