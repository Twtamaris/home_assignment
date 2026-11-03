import React, { useEffect, useState, useCallback } from 'react'
import { X, Package, Calendar, RefreshCw, Clock, Loader2, AlertTriangle } from 'lucide-react'
import { Order, Booking, User, Organisation, AdminOrder, AdminBooking } from '../types'
import { api } from '../api'
import { npr, studioWallClock, isPastStudioTime } from '../format'

interface CustomerDrawerProps {
  isOpen: boolean
  onClose: () => void
  user: User
  org: Organisation
  /** Bumped by the chat when a card is confirmed, so an open panel shows the change at once. */
  refreshKey: number
}

const BADGE: Record<string, string> = {
  pending: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  confirmed: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  shipped: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  delivered: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  completed: 'bg-slate-600/30 text-slate-300 border-slate-500/40',
  cancelled: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  rescheduled: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
}

const Badge: React.FC<{ status: string }> = ({ status }) => (
  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${BADGE[status] || 'bg-slate-800 text-slate-300 border-slate-700'}`}>{status}</span>
)

const NEXT: Record<string, { to: string; label: string; tone: string }[]> = {
  pending: [
    { to: 'confirmed', label: 'Confirm', tone: 'bg-blue-600 hover:bg-blue-500' },
    { to: 'cancelled', label: 'Cancel', tone: 'bg-rose-700 hover:bg-rose-600' },
  ],
  confirmed: [
    { to: 'shipped', label: 'Ship', tone: 'bg-purple-600 hover:bg-purple-500' },
    { to: 'cancelled', label: 'Cancel', tone: 'bg-rose-700 hover:bg-rose-600' },
  ],
  shipped: [{ to: 'delivered', label: 'Deliver', tone: 'bg-emerald-600 hover:bg-emerald-500' }],
}

export const CustomerDrawer: React.FC<CustomerDrawerProps> = ({ isOpen, onClose, user, org, refreshKey }) => {
  const [orders, setOrders] = useState<(Order | AdminOrder)[]>([])
  const [bookings, setBookings] = useState<(Booking | AdminBooking)[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [advancingId, setAdvancingId] = useState<string | null>(null)
  const retail = org.agent_kind !== 'studio'
  const isAdmin = user.role === 'admin'

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (retail) setOrders(isAdmin ? await api.listAdminOrders() : await api.listOrders())
      else setBookings(isAdmin ? await api.listAdminBookings() : await api.listBookings())
    } catch (err: any) {
      setError(err.message || 'Could not load your records.')
    } finally {
      setLoading(false)
    }
  }, [retail, isAdmin])

  useEffect(() => {
    if (isOpen) loadData()
  }, [isOpen, refreshKey, loadData])

  const advance = async (orderId: string, status: string) => {
    setAdvancingId(orderId)
    setError(null)
    try {
      await api.advanceOrderStatus(orderId, status)
      await loadData()
    } catch (err: any) {
      setError(err.message || 'Failed to change the status')
    } finally {
      setAdvancingId(null)
    }
  }

  if (!isOpen) return null

  const title = isAdmin ? (retail ? 'All orders' : 'All bookings') : retail ? 'My orders' : 'My bookings'
  const empty = retail ? (isAdmin ? 'No orders in this organisation yet.' : 'No orders yet. Ask the assistant to place one.') : (isAdmin ? 'No bookings in this organisation yet.' : 'No appointments yet. Ask the assistant to book one.')

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-6 sm:pl-10" onClick={(e) => e.stopPropagation()}>
        <div className="w-screen max-w-md bg-slate-900 border-l border-slate-800 text-slate-100 flex flex-col shadow-2xl">
          <div className="p-4 border-b border-slate-800 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="p-2 rounded-xl text-white shrink-0" style={{ backgroundColor: org.primary_color }}>
                {retail ? <Package className="w-5 h-5" /> : <Calendar className="w-5 h-5" />}
              </div>
              <div className="min-w-0">
                <h2 className="font-semibold text-sm text-white">{title}</h2>
                <p className="text-xs text-slate-400 truncate">{isAdmin ? `${org.name} (admin)` : user.email}</p>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={loadData} aria-label="Refresh" className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
              <button onClick={onClose} aria-label="Close" className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition">
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {error && (
              <div role="alert" className="flex items-start gap-2 p-3 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0" /><span>{error}</span>
              </div>
            )}
            {loading && orders.length + bookings.length === 0 ? (
              <div className="flex items-center justify-center gap-2 h-40 text-xs text-slate-400" role="status"><Loader2 className="w-4 h-4 animate-spin" />Loading...</div>
            ) : retail ? (
              orders.length === 0 && !error ? (
                <div className="text-center py-12 text-slate-400 text-xs">{empty}</div>
              ) : (
                orders.map((o) => {
                  const admin = o as AdminOrder
                  return (
                    <div key={o.id} className="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 space-y-2">
                      <div className="flex justify-between items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-white">#{o.id}</span><Badge status={o.status} />
                      </div>
                      {isAdmin && admin.customer_name && <div className="text-[11px] text-slate-400">{admin.customer_name} · {admin.customer_email}</div>}
                      <div className="text-xs space-y-1">
                        {o.items?.map((item, idx) => (
                          <div key={idx} className="flex justify-between gap-3 text-slate-300">
                            <span className="min-w-0 break-words">{item.name} × {item.quantity}</span>
                            <span className="font-mono text-slate-400 whitespace-nowrap">{npr(item.subtotal)}</span>
                          </div>
                        ))}
                      </div>
                      {o.shipping_address && <div className="text-[11px] text-slate-500 break-words">Deliver to: {o.shipping_address}</div>}
                      <div className="pt-2 border-t border-slate-700/60 flex justify-between items-center text-xs">
                        <span className="text-slate-400">Total</span><span className="font-bold text-emerald-400">{npr(o.total_price)}</span>
                      </div>
                      {isAdmin && NEXT[o.status] && (
                        <div className="pt-2 border-t border-slate-700/40">
                          <span className="text-[10px] text-amber-400 uppercase tracking-wider font-semibold block mb-1">Move order forward</span>
                          <div className="flex gap-1.5 flex-wrap">
                            {NEXT[o.status].map((step) => (
                              <button key={step.to} disabled={advancingId === o.id} onClick={() => advance(o.id, step.to)}
                                className={`px-2.5 py-1.5 rounded text-[11px] font-medium text-white transition disabled:opacity-50 ${step.tone}`}>
                                {step.label} → {step.to}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })
              )
            ) : bookings.length === 0 && !error ? (
              <div className="text-center py-12 text-slate-400 text-xs">{empty}</div>
            ) : (
              bookings.map((b) => {
                const admin = b as AdminBooking
                const mine = b as Booking
                return (
                  <div key={b.id} className="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 space-y-1.5">
                    <div className="flex justify-between items-center gap-2"><span className="font-mono text-xs font-semibold text-white">#{b.id}</span><Badge status={b.status !== 'cancelled' && isPastStudioTime(b.start_time) ? 'completed' : b.status} /></div>
                    <div className="text-xs">
                      <div className="font-medium text-slate-200">{admin.service_name || mine.service_name || mine.service_id}</div>
                      <div className="text-slate-400">with {admin.practitioner_name || mine.practitioner_name || mine.practitioner_id}</div>
                      {isAdmin && admin.customer_name && <div className="text-slate-400">for {admin.customer_name}</div>}
                      <div className="text-indigo-300 mt-1 flex items-center gap-1"><Clock className="w-3 h-3 text-indigo-400" /><span>{studioWallClock(b.start_time)}</span></div>
                      {b.cancellation_fee > 0 && <div className="text-[11px] text-rose-400 mt-1">Cancellation fee: {npr(b.cancellation_fee)}</div>}
                    </div>
                  </div>
                )
              })
            )}
            {!retail && <p className="text-[10px] text-slate-500 text-center pt-1">All times are Asia/Kathmandu (UTC+05:45)</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
