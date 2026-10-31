import React, { useEffect, useState } from 'react'
import { X, Package, Calendar, RefreshCw, ChevronRight, CheckCircle2, Truck, Box, Clock } from 'lucide-react'
import { Order, Booking, User, Organisation } from '../types'
import { api } from '../api'

interface CustomerDrawerProps {
  isOpen: boolean
  onClose: () => void
  user: User
  org: Organisation
}

export const CustomerDrawer: React.FC<CustomerDrawerProps> = ({ isOpen, onClose, user, org }) => {
  const [orders, setOrders] = useState<Order[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(false)
  const [advancingId, setAdvancingId] = useState<string | null>(null)
  const isOrgA = org.id === 'org_a'

  useEffect(() => {
    if (isOpen) {
      loadData()
    }
  }, [isOpen, org.id])

  const loadData = async () => {
    setLoading(true)
    try {
      if (isOrgA) {
        const o = await api.listOrders()
        setOrders(o)
      } else {
        const b = await api.listBookings()
        setBookings(b)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleAdvanceStatus = async (orderId: string, nextStatus: string) => {
    setAdvancingId(orderId)
    try {
      await api.advanceOrderStatus(orderId, nextStatus)
      await loadData()
    } catch (err: any) {
      alert(err.message || 'Failed to advance status')
    } finally {
      setAdvancingId(null)
    }
  }

  if (!isOpen) return null

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'pending':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">PENDING</span>
      case 'confirmed':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">CONFIRMED</span>
      case 'shipped':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30">SHIPPED</span>
      case 'delivered':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">DELIVERED</span>
      case 'cancelled':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">CANCELLED</span>
      case 'rescheduled':
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">RESCHEDULED</span>
      default:
        return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300">{status}</span>
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md bg-slate-900 border-l border-slate-800 text-slate-100 flex flex-col shadow-2xl">
          {/* Header */}
          <div className="p-4 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div
                className="p-2 rounded-xl text-white"
                style={{ backgroundColor: org.primary_color }}
              >
                {isOrgA ? <Package className="w-5 h-5" /> : <Calendar className="w-5 h-5" />}
              </div>
              <div>
                <h2 className="font-semibold text-sm text-white">
                  {isOrgA ? 'My Orders' : 'My Bookings'}
                </h2>
                <p className="text-xs text-slate-400">{user.email}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={loadData}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
                title="Refresh"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {loading ? (
              <div className="flex items-center justify-center h-40 text-xs text-slate-400">
                Loading records...
              </div>
            ) : isOrgA ? (
              orders.length === 0 ? (
                <div className="text-center py-12 text-slate-400 text-xs">No orders placed yet.</div>
              ) : (
                orders.map((o) => (
                  <div key={o.id} className="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="font-mono text-xs font-semibold text-white">#{o.id}</span>
                      {getStatusBadge(o.status)}
                    </div>

                    <div className="text-xs space-y-1">
                      {o.items?.map((item, idx) => (
                        <div key={idx} className="flex justify-between text-slate-300">
                          <span>{item.name} × {item.quantity}</span>
                          <span className="font-mono text-slate-400">NPR {item.subtotal?.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>

                    <div className="pt-2 border-t border-slate-700/60 flex justify-between items-center text-xs">
                      <span className="text-slate-400">Total</span>
                      <span className="font-bold text-emerald-400">NPR {o.total_price.toFixed(2)}</span>
                    </div>

                    {/* Admin Status Advancement Controls */}
                    {user.role === 'admin' && (
                      <div className="pt-2 border-t border-slate-700/40">
                        <span className="text-[10px] text-amber-400 uppercase tracking-wider font-semibold block mb-1">
                          Admin Order Status Controls:
                        </span>
                        <div className="flex gap-1.5 flex-wrap">
                          {o.status === 'pending' && (
                            <button
                              disabled={advancingId === o.id}
                              onClick={() => handleAdvanceStatus(o.id, 'confirmed')}
                              className="px-2 py-1 rounded text-[10px] font-medium bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50"
                            >
                              Advance → Confirmed
                            </button>
                          )}
                          {o.status === 'confirmed' && (
                            <button
                              disabled={advancingId === o.id}
                              onClick={() => handleAdvanceStatus(o.id, 'shipped')}
                              className="px-2 py-1 rounded text-[10px] font-medium bg-purple-600 hover:bg-purple-500 text-white transition disabled:opacity-50"
                            >
                              Advance → Shipped
                            </button>
                          )}
                          {o.status === 'shipped' && (
                            <button
                              disabled={advancingId === o.id}
                              onClick={() => handleAdvanceStatus(o.id, 'delivered')}
                              className="px-2 py-1 rounded text-[10px] font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition disabled:opacity-50"
                            >
                              Advance → Delivered
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))
              )
            ) : bookings.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-xs">No appointments booked yet.</div>
            ) : (
              bookings.map((b) => (
                <div key={b.id} className="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="font-mono text-xs font-semibold text-white">#{b.id}</span>
                    {getStatusBadge(b.status)}
                  </div>
                  <div className="text-xs">
                    <div className="font-medium text-slate-200">{b.service_name || b.service_id}</div>
                    <div className="text-slate-400">with {b.practitioner_name || b.practitioner_id}</div>
                    <div className="text-indigo-300 mt-1 flex items-center gap-1">
                      <Clock className="w-3 h-3 text-indigo-400" />
                      <span>{b.formatted_time || b.start_time}</span>
                    </div>
                    {b.cancellation_fee > 0 && (
                      <div className="text-[11px] text-rose-400 mt-1">
                        Cancellation fee: NPR {b.cancellation_fee.toFixed(2)}
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
