import React, { useEffect, useState } from 'react'
import { X, TrendingUp, Users, ShoppingBag, Clock, BarChart3, ChevronDown, Info, AlertTriangle, Loader2 } from 'lucide-react'
import { Organisation } from '../types'
import { api } from '../api'
import { npr } from '../format'

interface AdminAnalyticsModalProps {
  isOpen: boolean
  onClose: () => void
  org: Organisation
}

/** "Last 30 days: 2026-10-04 ... (Asia/Kathmandu ...)" -> "Last 30 days". The full text stays in the definitions section. */
const shortWindow = (label?: string) => (label ? label.split(':')[0] : '')

const Stat: React.FC<{ label: string; value: React.ReactNode; sub?: string; window: string; icon: React.ReactNode }> = ({ label, value, sub, window, icon }) => (
  <div className="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60">
    <div className="flex items-center justify-between text-slate-400 text-xs mb-1"><span>{label}</span>{icon}</div>
    <div className="text-2xl font-bold text-white leading-tight">{value}</div>
    {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    <div className="mt-2 inline-block px-2 py-0.5 rounded-full text-[10px] bg-slate-900 border border-slate-700 text-slate-400">{window}</div>
  </div>
)

/** A ranked list drawn as horizontal bars, so the shape of the data is visible at a glance. */
const Bars: React.FC<{ rows: { label: string; value: number; note?: string }[]; unit: string; color: string; empty: string }> = ({ rows, unit, color, empty }) => {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (rows.length === 0) return <p className="text-xs text-slate-500 py-4">{empty}</p>
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label}>
          <div className="flex justify-between gap-3 text-xs mb-1">
            <span className="text-slate-200 truncate">{r.label}</span>
            <span className="text-slate-400 whitespace-nowrap font-mono">{r.value} {unit}{r.note ? ` · ${r.note}` : ''}</span>
          </div>
          <div className="h-2 rounded-full bg-slate-900 overflow-hidden" role="presentation">
            <div className="h-full rounded-full" style={{ width: `${(r.value / max) * 100}%`, backgroundColor: color }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

const Panel: React.FC<{ title: string; subtitle: string; children: React.ReactNode }> = ({ title, subtitle, children }) => (
  <section className="p-5 rounded-2xl bg-slate-800/40 border border-slate-700/50">
    <h3 className="text-sm font-semibold text-white">{title}</h3>
    <p className="text-[11px] text-slate-400 mb-4">{subtitle}</p>
    {children}
  </section>
)

export const AdminAnalyticsModal: React.FC<AdminAnalyticsModalProps> = ({ isOpen, onClose, org }) => {
  const [activity, setActivity] = useState<any>(null)
  const [clients, setClients] = useState<any>(null)
  const [conversion, setConversion] = useState<any>(null)
  const [topItems, setTopItems] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const retail = org.agent_kind !== 'studio' // retail metrics vs studio metrics, chosen by configuration

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [act, cli, conv, top] = await Promise.all([
        api.getAdminActivitySummary(), api.getAdminClientsToday(), api.getAdminConversionRate(), api.getAdminTopItems(),
      ])
      setActivity(act); setClients(cli); setConversion(conv); setTopItems(top)
    } catch (err: any) {
      setError(err.message || 'Could not load the analytics.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) load()
  }, [isOpen, org.id])

  if (!isOpen) return null
  const m = activity?.metrics || {}
  const window30 = shortWindow(activity?.time_window)
  const people: any[] = m.practitioner_utilisation || []

  return (
    <div className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-black/70 backdrop-blur-sm p-3 sm:p-4 overflow-y-auto" onClick={onClose} role="dialog" aria-modal="true" aria-label="Analytics">
      <div className="relative w-full max-w-4xl rounded-2xl bg-slate-900 border border-slate-700/80 p-4 sm:p-6 shadow-2xl text-slate-100 max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <button onClick={onClose} aria-label="Close" className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"><X className="w-5 h-5" /></button>

        <header className="flex items-center gap-3 mb-5 pr-8">
          <div className="p-3 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20"><BarChart3 className="w-6 h-6" /></div>
          <div>
            <h2 className="text-lg font-bold text-white">Analytics</h2>
            <p className="text-xs text-slate-400">{org.name} only. Read-only. Times are Asia/Kathmandu.</p>
          </div>
        </header>

        {error && (
          <div role="alert" className="flex items-center gap-2 p-3 mb-4 rounded-xl bg-rose-950/40 border border-rose-500/30 text-rose-300 text-xs">
            <AlertTriangle className="w-4 h-4 shrink-0" /><span className="flex-1">{error}</span>
            <button onClick={load} className="px-2 py-1 rounded bg-slate-800 text-white">Retry</button>
          </div>
        )}

        {loading ? (
          <div className="py-20 flex items-center justify-center gap-2 text-sm text-slate-400" role="status"><Loader2 className="w-4 h-4 animate-spin" />Loading live figures...</div>
        ) : !error && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {retail ? (
                <Stat label="Gross revenue" icon={<TrendingUp className="w-4 h-4 text-emerald-400" />} window={window30}
                  value={npr(m.gross_revenue_npr).replace('.00', '')} sub={`Average order ${npr(m.average_order_value_npr).replace('.00', '')}`} />
              ) : (
                <Stat label="Bookings" icon={<TrendingUp className="w-4 h-4 text-emerald-400" />} window={window30}
                  value={m.total_bookings ?? 0} sub={`${m.cancellations ?? 0} cancelled (${m.cancellation_rate_percentage ?? 0}%)`} />
              )}
              <Stat label="Customers who chatted" icon={<Users className="w-4 h-4 text-blue-400" />} window="Today"
                value={clients?.unique_customers_chatted ?? 0} sub={`${clients?.new_signups_today ?? 0} new sign-ups`} />
              <Stat label="Conversion rate" icon={<ShoppingBag className="w-4 h-4 text-purple-400" />} window={shortWindow(conversion?.time_window)}
                value={<span className="text-purple-300">{conversion?.conversion_rate_percentage ?? 0}%</span>}
                sub={`${conversion?.successful_conversations ?? 0} of ${conversion?.total_conversations ?? 0} chats`} />
              {retail ? (
                <Stat label="Orders" icon={<Clock className="w-4 h-4 text-amber-400" />} window={window30}
                  value={m.total_orders ?? 0} sub={`${m.paid_order_count ?? 0} confirmed or later`} />
              ) : (
                <Stat label="Busiest practitioner" icon={<Clock className="w-4 h-4 text-amber-400" />} window={window30}
                  value={<span className="text-lg">{m.busiest_practitioner || 'None yet'}</span>} sub={`${people.length} practitioners`} />
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {retail ? (
                <>
                  <Panel title="Best sellers" subtitle="Units sold, all time (cancelled orders excluded)">
                    <Bars color="#a855f7" unit="sold" empty="No sales yet."
                      rows={(topItems?.top_items || []).slice(0, 5).map((i: any) => ({ label: i.name, value: i.units_sold }))} />
                  </Panel>
                  <Panel title="Stock watchlist" subtitle="5 or fewer units left, or has sold out before">
                    <Bars color="#f43f5e" unit="left" empty="Nothing is running low."
                      rows={(topItems?.secondary_items || []).slice(0, 5).map((i: any) => ({
                        label: i.name, value: i.current_stock, note: i.historical_stockouts ? `${i.historical_stockouts} past stock-out` : undefined }))} />
                  </Panel>
                </>
              ) : (
                <>
                  <Panel title="Most-booked services" subtitle="Bookings per service, all time (cancelled excluded)">
                    <Bars color="#a855f7" unit="bookings" empty="No bookings yet."
                      rows={(topItems?.top_items || []).filter((i: any) => i.total_bookings > 0).slice(0, 5).map((i: any) => ({ label: i.service_name, value: i.total_bookings }))} />
                  </Panel>
                  <Panel title="Busiest start times" subtitle="Bookings by start hour, Kathmandu time">
                    <Bars color="#14b8a6" unit="bookings" empty="No bookings yet."
                      rows={(topItems?.secondary_items || []).slice(0, 5).map((i: any) => ({ label: i.hour, value: i.bookings }))} />
                  </Panel>
                  <div className="md:col-span-2">
                    <Panel title="Practitioner utilisation" subtitle={`Non-cancelled sessions and booked hours, ${window30.toLowerCase()}`}>
                      <Bars color="#6366f1" unit="sessions" empty="No sessions yet."
                        rows={people.map((p) => ({ label: p.practitioner_name, value: p.total_sessions, note: `${p.booked_hours} h` }))} />
                    </Panel>
                  </div>
                </>
              )}
            </div>

            {/* The brief asks for a stated window and definition behind every number. Windows are on each figure; the full wording is here. */}
            <details className="group rounded-xl bg-slate-950/60 border border-slate-800 text-xs text-slate-400">
              <summary className="flex items-center gap-2 px-4 py-3 cursor-pointer text-slate-200 font-semibold list-none">
                <Info className="w-4 h-4 text-purple-400" />How these numbers are calculated
                <ChevronDown className="w-4 h-4 ml-auto transition group-open:rotate-180" />
              </summary>
              <dl className="px-4 pb-4 space-y-3">
                {[
                  ['Activity', activity?.time_window, activity?.definition],
                  ['Customers today', clients?.date, clients?.definition],
                  ['Conversion', conversion?.time_window, conversion?.definition],
                  ['Rankings', topItems?.time_window, topItems?.definition],
                ].map(([name, win, def]) => (
                  <div key={name as string}>
                    <dt className="text-slate-200 font-medium">{name}</dt>
                    <dd className="text-slate-500">{win}</dd>
                    <dd className="mt-0.5 leading-relaxed">{def}</dd>
                  </div>
                ))}
                <p className="text-slate-500 pt-1">Every query is restricted to your organisation. Customers cannot open this panel (HTTP 403).</p>
              </dl>
            </details>
          </div>
        )}
      </div>
    </div>
  )
}
