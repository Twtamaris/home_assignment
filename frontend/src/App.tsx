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

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-400 gap-3">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs">Initializing multi-tenant agent session...</span>
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
