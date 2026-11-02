import React, { useState, useEffect } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { ChatPage } from './pages/ChatPage'

function AppContent() {
  const { user, currentOrg, loading, setOrganisation } = useAuth()
  const [currentPage, setCurrentPage] = useState<'login' | 'signup'>('login')
  const [orgSlug, setOrgSlug] = useState('himali-tea')

  // Parse path for /a/:orgSlug or query
  useEffect(() => {
    const path = window.location.pathname
    const match = path.match(/\/a\/([a-zA-Z0-9_-]+)/)
    if (match && match[1]) {
      setOrgSlug(match[1])
    }
  }, [])

  const requestedSlug = (() => {
    const match = window.location.pathname.match(/\/a\/([a-zA-Z0-9_-]+)/)
    return match ? match[1] : null
  })()

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-400 gap-3">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs">Initializing multi-tenant agent session...</span>
      </div>
    )
  }

  // Tenant Boundary Guard: If authenticated user navigates to another org URL
  if (user && currentOrg && requestedSlug && requestedSlug !== currentOrg.slug) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-300 p-6 text-center">
        <div className="max-w-md w-full bg-slate-900 border border-red-500/30 rounded-2xl p-8 shadow-2xl space-y-4">
          <div className="w-12 h-12 bg-red-500/10 text-red-400 rounded-full flex items-center justify-center mx-auto text-xl font-bold">
            !
          </div>
          <h2 className="text-xl font-bold text-white">Cross-Tenant Access Blocked</h2>
          <p className="text-sm text-slate-400">
            Your authenticated session belongs to <strong className="text-emerald-400">{currentOrg.name}</strong> (<code className="text-xs bg-slate-800 px-1 py-0.5 rounded">{currentOrg.slug}</code>).
            You are strictly blocked from accessing <strong className="text-red-400">/a/{requestedSlug}</strong>.
          </p>
          <div className="pt-2">
            <button
              onClick={() => {
                window.location.replace(`/a/${currentOrg.slug}`)
              }}
              className="w-full py-2.5 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-xl text-sm transition-colors"
            >
              Return to Your Assigned Workspace
            </button>
          </div>
        </div>
      </div>
    )
  }

  // If user is authenticated and org is loaded, display ChatPage
  if (user && currentOrg) {
    return <ChatPage user={user} org={currentOrg} />
  }

  if (currentPage === 'signup' && currentOrg) {
    return (
      <SignupPage
        onNavigateToLogin={() => setCurrentPage('login')}
        currentOrg={currentOrg}
      />
    )
  }

  return (
    <LoginPage
      currentOrgSlug={orgSlug}
      onSwitchOrgSlug={(slug) => {
        setOrgSlug(slug)
        window.history.replaceState({}, '', `/a/${slug}`)
      }}
      onNavigateToSignup={() => setCurrentPage('signup')}
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
