import React, { useEffect, useState } from 'react'
import { X, TrendingUp, Users, ShoppingBag, Clock, AlertCircle, BarChart3 } from 'lucide-react'
import { Organisation } from '../types'
import { api } from '../api'

interface AdminAnalyticsModalProps {
  isOpen: boolean
  onClose: () => void
  org: Organisation
}

export const AdminAnalyticsModal: React.FC<AdminAnalyticsModalProps> = ({ isOpen, onClose, org }) => {
  const [activity, setActivity] = useState<any>(null)
  const [clients, setClients] = useState<any>(null)
  const [conversion, setConversion] = useState<any>(null)
  const [topItems, setTopItems] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (isOpen) {
      loadMetrics()
    }
  }, [isOpen, org.id])

  const loadMetrics = async () => {
    setLoading(true)
    try {
      const [act, cli, conv, top] = await Promise.all([
        api.getAdminActivitySummary(),
        api.getAdminClientsToday(),
        api.getAdminConversionRate(),
        api.getAdminTopItems(),
      ])
      setActivity(act)
      setClients(cli)
      setConversion(conv)
      setTopItems(top)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null
  const isOrgA = org.id === 'org_a'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 overflow-y-auto animate-in fade-in">
      <div className="relative w-full max-w-4xl rounded-2xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl text-slate-100 max-h-[90vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-6 pb-4 border-b border-slate-800">
          <div className="p-3 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <BarChart3 className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <span>Admin Analytics & Intelligence</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 font-normal">
                {org.name}
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Read-only performance metrics scoped strictly to your organisation ID ({org.id})
            </p>
          </div>
        </div>

        {loading ? (
          <div className="py-20 text-center text-sm text-slate-400">Loading live analytics...</div>
        ) : (
          <div className="space-y-6">
            {/* Top 4 KPI Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Card 1: Revenue or Bookings */}
              <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60">
                <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                  <span>{isOrgA ? 'Gross Revenue' : 'Total Bookings'}</span>
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                </div>
                <div className="text-xl font-bold text-white">
                  {isOrgA
                    ? `NPR ${activity?.metrics?.gross_revenue_npr?.toLocaleString() || '0'}`
                    : `${activity?.metrics?.total_bookings || 0} Sessions`}
                </div>
                <div className="text-[11px] text-slate-400 mt-1 truncate">
                  {isOrgA ? `AOV: NPR ${activity?.metrics?.average_order_value_npr?.toFixed(2)}` : `Cancel Rate: ${activity?.metrics?.cancellation_rate_percentage}%`}
                </div>
              </div>

              {/* Card 2: Clients Today */}
              <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60">
                <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                  <span>Chatted Today</span>
                  <Users className="w-4 h-4 text-blue-400" />
                </div>
                <div className="text-xl font-bold text-white">
                  {clients?.unique_customers_chatted ?? 0} Customers
                </div>
                <div className="text-[11px] text-slate-400 mt-1">
                  +{clients?.new_signups_today ?? 0} new sign-ups today
                </div>
              </div>

              {/* Card 3: Conversion Rate */}
              <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60">
                <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                  <span>Conversion Rate</span>
                  <ShoppingBag className="w-4 h-4 text-purple-400" />
                </div>
                <div className="text-xl font-bold text-purple-400">
                  {conversion?.conversion_rate_percentage ?? 0}%
                </div>
                <div className="text-[11px] text-slate-400 mt-1 truncate">
                  {conversion?.successful_conversations} of {conversion?.total_conversations} chats
                </div>
              </div>

              {/* Card 4: Orders/Utilisation */}
              <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60">
                <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
                  <span>{isOrgA ? 'Total Orders' : 'Practitioners'}</span>
                  <Clock className="w-4 h-4 text-amber-400" />
                </div>
                <div className="text-xl font-bold text-white">
                  {isOrgA ? activity?.metrics?.total_orders : activity?.metrics?.practitioner_utilisation?.length}
                </div>
                <div className="text-[11px] text-slate-400 mt-1">
                  {isOrgA ? `${activity?.metrics?.paid_order_count} confirmed` : 'All certified'}
                </div>
              </div>
            </div>

            {/* Detailed Breakdowns */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Section 1: Top Items / Services */}
              <div className="p-5 rounded-2xl bg-slate-800/40 border border-slate-700/50">
                <h3 className="text-sm font-semibold text-white mb-1">
                  {isOrgA ? 'Best-Selling Teas & Teaware' : 'Most-Booked Therapies'}
                </h3>
                <p className="text-[11px] text-slate-400 mb-3">{topItems?.definition}</p>

                <div className="space-y-2">
                  {topItems?.top_items?.slice(0, 4).map((item: any, idx: number) => (
                    <div key={idx} className="flex justify-between items-center text-xs p-2 rounded-lg bg-slate-900/60">
                      <span className="font-medium text-slate-200">
                        {item.name || item.service_name}
                      </span>
                      <span className="text-purple-300 font-mono">
                        {isOrgA ? `${item.units_sold} sold` : `${item.total_bookings} bookings`}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Section 2: Secondary Insights (Low stock / Peak hours) */}
              <div className="p-5 rounded-2xl bg-slate-800/40 border border-slate-700/50">
                <h3 className="text-sm font-semibold text-white mb-1">
                  {isOrgA ? 'Low Inventory Watchlist' : 'Peak Studio Hours'}
                </h3>
                <p className="text-[11px] text-slate-400 mb-3">
                  {isOrgA ? 'Products with critical inventory (<= 5 remaining)' : 'Busiest appointment hours in Kathmandu time'}
                </p>

                <div className="space-y-2">
                  {isOrgA
                    ? topItems?.secondary_items?.slice(0, 4).map((item: any, idx: number) => (
                        <div key={idx} className="flex justify-between items-center text-xs p-2 rounded-lg bg-slate-900/60">
                          <span className="text-slate-300">{item.name}</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                            {item.current_stock} left
                          </span>
                        </div>
                      ))
                    : topItems?.secondary_items?.slice(0, 4).map((item: any, idx: number) => (
                        <div key={idx} className="flex justify-between items-center text-xs p-2 rounded-lg bg-slate-900/60">
                          <span className="text-slate-300">{item.hour}</span>
                          <span className="text-teal-300 font-mono">{item.bookings} bookings</span>
                        </div>
                      ))}
                </div>
              </div>
            </div>

            {/* Definitions & Compliance Footer */}
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-[11px] text-slate-400 space-y-1">
              <div className="flex items-center gap-1.5 text-slate-300 font-semibold mb-1">
                <AlertCircle className="w-3.5 h-3.5 text-purple-400" />
                <span>Audit & Metrics Methodology:</span>
              </div>
              <p>• <strong>Activity Time Window:</strong> {activity?.time_window}</p>
              <p>• <strong>Activity Definition:</strong> {activity?.definition}</p>
              <p>• <strong>Conversion Formula:</strong> {conversion?.definition}</p>
              <p>• <strong>Tenant Enforcement:</strong> Zero data sharing across tenants; queries execute with explicit <code>WHERE org_id = current_user.org_id</code> constraint.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
