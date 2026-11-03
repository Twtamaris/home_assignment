import React from 'react'
import { LogOut, BarChart3, Package, Calendar, Menu, Sparkles, Shield } from 'lucide-react'
import { Organisation, User } from '../types'

interface NavbarProps {
  org: Organisation
  user: User
  onOpenDrawer: () => void
  onOpenAdminModal: () => void
  onToggleSidebar: () => void
  onLogout: () => void
}

export const Navbar: React.FC<NavbarProps> = ({
  org,
  user,
  onOpenDrawer,
  onOpenAdminModal,
  onToggleSidebar,
  onLogout,
}) => {
  const isRetail = org.agent_kind !== 'studio'

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md px-4 flex items-center justify-between z-30 shrink-0">
      {/* Left Branding */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="lg:hidden p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition"
          aria-label="Toggle navigation"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-2xl flex items-center justify-center text-white shadow-md font-bold text-lg"
            style={{
              background: `linear-gradient(135deg, ${org.primary_color}, ${org.secondary_color})`,
              boxShadow: `0 4px 14px ${org.primary_color}40`,
            }}
          >
            {org.name.charAt(0)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-sm sm:text-base text-white leading-tight">{org.name}</h1>
              <span
                className="hidden sm:inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold text-white/90"
                style={{ backgroundColor: `${org.primary_color}cc` }}
              >
                {org.agent_name}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden md:block">{org.tagline}</p>
          </div>
        </div>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Customer Drawer (My Orders / My Bookings) */}
        <button
          onClick={onOpenDrawer}
          aria-label={user.role === 'admin' ? (isRetail ? 'Orders' : 'Bookings') : isRetail ? 'My orders' : 'My bookings'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/60 transition active:scale-95"
        >
          {isRetail ? <Package className="w-4 h-4 text-emerald-400" /> : <Calendar className="w-4 h-4 text-teal-400" />}
          <span className="hidden sm:inline">{user.role === 'admin' ? (isRetail ? 'Orders' : 'Bookings') : isRetail ? 'My Orders' : 'My Bookings'}</span>
        </button>

        {/* Admin Analytics Button */}
        {user.role === 'admin' && (
          <button
            onClick={onOpenAdminModal}
            aria-label="Analytics"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-purple-950/60 hover:bg-purple-900/80 text-purple-300 border border-purple-500/40 transition active:scale-95 shadow-sm"
          >
            <BarChart3 className="w-4 h-4 text-purple-400" />
            <span className="hidden sm:inline">Analytics</span>
          </button>
        )}

        {/* User Pill & Role */}
        <div className="hidden sm:flex items-center gap-2 pl-2 border-l border-slate-800">
          <div className="text-right">
            <div className="text-xs font-medium text-slate-200">{user.name}</div>
            <div className="text-[10px] text-slate-400 flex items-center justify-end gap-1">
              {user.role === 'admin' && <Shield className="w-3 h-3 text-amber-400" />}
              <span className="capitalize">{user.role}</span>
            </div>
          </div>
        </div>

        {/* Logout */}
        <button
          onClick={onLogout}
          className="p-2 rounded-xl text-slate-400 hover:text-rose-400 hover:bg-slate-800/80 transition"
          title="Sign out" aria-label="Sign out"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  )
}

