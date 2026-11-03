import React from 'react'
import {
  CheckCircle2, Clock, MapPin, Calendar, AlertTriangle, ArrowRight, Package, Loader2, XCircle, RefreshCcw, Ban, ListOrdered,
} from 'lucide-react'
import { ProposalState } from '../types'
import { npr, parseServerUtc, studioDateTime, studioDay, studioTime, studioWallClock } from '../format'

interface RichCardProps {
  card: any
  /** Live state of the proposal behind a Confirm card. Undefined while it is being fetched. */
  proposal?: ProposalState
  /** True while a confirm or reject request for this card is in flight. */
  busy?: boolean
  onConfirm?: (proposalId: string) => void
  onReject?: (proposalId: string) => void
  /** Sends a message on the customer's behalf, for slot buttons. */
  onAction?: (text: string) => void
}

type View = 'loading' | 'pending' | 'confirmed' | 'rejected' | 'expired' | 'stale' | 'failed'

function viewOf(card: any, proposal?: ProposalState): View {
  if (!card.proposal_id) return 'failed'
  if (!proposal) return 'loading'
  if (proposal.status === 'pending' && proposal.expires_at && parseServerUtc(proposal.expires_at).getTime() < Date.now()) return 'expired'
  switch (proposal.status) {
    case 'pending': return 'pending'
    case 'confirmed': return 'confirmed'
    case 'rejected': return 'rejected'
    case 'expired': return 'expired'
    case 'stale': return 'stale'
    default: return 'failed'
  }
}

const BANNER: Record<Exclude<View, 'pending' | 'loading'>, { text: string; tone: string; icon: React.ReactNode }> = {
  confirmed: { text: 'Confirmed. This change has been saved.', tone: 'text-emerald-300 bg-emerald-950/40 border-emerald-500/30', icon: <CheckCircle2 className="w-4 h-4" /> },
  rejected: { text: 'Discarded. Nothing was changed.', tone: 'text-slate-300 bg-slate-800/60 border-slate-600/40', icon: <XCircle className="w-4 h-4" /> },
  expired: { text: 'This summary expired. Ask again for a fresh one.', tone: 'text-amber-300 bg-amber-950/30 border-amber-500/30', icon: <Clock className="w-4 h-4" /> },
  stale: { text: 'Replaced by an updated summary because something changed.', tone: 'text-amber-300 bg-amber-950/30 border-amber-500/30', icon: <RefreshCcw className="w-4 h-4" /> },
  failed: { text: 'This could not be completed. Nothing was changed.', tone: 'text-rose-300 bg-rose-950/30 border-rose-500/30', icon: <AlertTriangle className="w-4 h-4" /> },
}

function ConfirmBar({ card, view, busy, label, tone, onConfirm, onReject }: {
  card: any; view: View; busy?: boolean; label: string; tone: string
  onConfirm?: (id: string) => void; onReject?: (id: string) => void
}) {
  if (view === 'loading') {
    return <div className="flex items-center gap-2 text-[11px] text-slate-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Checking status...</div>
  }
  if (view !== 'pending') {
    const b = BANNER[view]
    return <div role="status" className={`flex items-center gap-2 text-xs rounded-lg border px-3 py-2 ${b.tone}`}>{b.icon}<span>{b.text}</span></div>
  }
  return (
    <div className="flex gap-2">
      <button
        onClick={() => onConfirm && onConfirm(card.proposal_id)}
        disabled={busy}
        className={`flex-1 py-2.5 px-4 rounded-xl text-xs font-semibold text-white shadow-md transition flex items-center justify-center gap-2 active:scale-98 disabled:opacity-60 ${tone}`}
      >
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
        <span>{busy ? 'Working...' : label}</span>
        {!busy && <ArrowRight className="w-3.5 h-3.5" />}
      </button>
      <button
        onClick={() => onReject && onReject(card.proposal_id)}
        disabled={busy}
        className="py-2.5 px-3 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition disabled:opacity-50"
      >
        Not now
      </button>
    </div>
  )
}

const Shell: React.FC<{ tone: string; title: React.ReactNode; icon: React.ReactNode; children: React.ReactNode; label: string }> = ({ tone, title, icon, children, label }) => (
  <section role="group" aria-label={label} className={`my-3 rounded-2xl border p-4 shadow-lg text-slate-100 w-full max-w-md ${tone}`}>
    <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/10 font-semibold text-sm">{icon}<span className="min-w-0 break-words">{title}</span></div>
    {children}
  </section>
)

function ItemRows({ items }: { items?: any[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="space-y-1.5 mb-3">
      {items.map((item, idx) => (
        <div key={idx} className="flex justify-between items-start gap-3 text-xs text-slate-300">
          <span className="font-medium text-slate-100 min-w-0 break-words">{item.name} <span className="text-emerald-400 whitespace-nowrap">× {item.quantity}</span></span>
          <span className="font-mono whitespace-nowrap">{npr(item.subtotal ?? item.unit_price * item.quantity)}</span>
        </div>
      ))}
    </div>
  )
}

const StatusPill: React.FC<{ status: string }> = ({ status }) => {
  const tone: Record<string, string> = {
    pending: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    confirmed: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    shipped: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    delivered: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    cancelled: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    rescheduled: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  }
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${tone[status] || 'bg-slate-700 text-slate-300 border-slate-600'}`}>{status}</span>
}

export const RichCard: React.FC<RichCardProps> = ({ card, proposal, busy, onConfirm, onReject, onAction }) => {
  if (!card || !card.type) return null

  switch (card.type) {
    case 'order_summary': {
      const view = viewOf(card, proposal)
      const changed = card.previous_total != null && Math.abs(card.previous_total - card.total_price) > 0.009
      return (
        <Shell label="Order summary" tone="bg-gradient-to-br from-emerald-950/40 to-slate-900 border-emerald-500/30" icon={<Package className="w-4 h-4 text-emerald-400" />} title={card.title || 'Please confirm your order'}>
          <ItemRows items={card.items} />
          {card.notes?.length > 0 && (
            <div className="mb-3 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-500/20 rounded-lg p-2 space-y-1">
              {card.notes.map((n: string, i: number) => <p key={i}>{n}</p>)}
            </div>
          )}
          <div className="pt-2 border-t border-slate-800 flex justify-between items-baseline mb-3">
            <span className="text-xs text-slate-400">Total{changed ? ` (was ${npr(card.previous_total)})` : ''}</span>
            <span className="text-base font-bold text-emerald-400">{npr(card.total_price)}</span>
          </div>
          {card.shipping_address && card.action !== 'cancel' && (
            <div className="flex items-start gap-1.5 text-[11px] text-slate-400 mb-3">
              <MapPin className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-px" /><span className="break-words">{card.shipping_address}</span>
            </div>
          )}
          <ConfirmBar card={card} view={view} busy={busy} onConfirm={onConfirm} onReject={onReject}
            label={card.confirm_label || 'Confirm Order'}
            tone={card.action === 'cancel' ? 'bg-rose-600 hover:bg-rose-500 shadow-rose-950/50' : 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-950/50'} />
        </Shell>
      )
    }

    case 'order_placed':
    case 'order_updated':
    case 'order_cancelled': {
      const cancelled = card.type === 'order_cancelled'
      const title = card.type === 'order_placed' ? 'Order placed' : cancelled ? 'Order cancelled' : 'Order updated'
      return (
        <Shell label={title} tone={cancelled ? 'bg-rose-950/20 border-rose-500/30' : 'bg-emerald-950/30 border-emerald-500/40'}
          icon={cancelled ? <Ban className="w-4 h-4 text-rose-400" /> : <CheckCircle2 className="w-4 h-4 text-emerald-400" />} title={title}>
          <div className="flex justify-between items-center text-xs mb-2">
            <span className="font-mono font-bold text-white">#{card.order_id}</span><StatusPill status={card.status} />
          </div>
          <ItemRows items={card.items} />
          {card.shipping_address && <div className="flex items-start gap-1.5 text-[11px] text-slate-400 mb-2"><MapPin className="w-3.5 h-3.5 shrink-0 mt-px" /><span className="break-words">{card.shipping_address}</span></div>}
          <div className="text-xs text-slate-400 flex justify-between"><span>Total</span><span className="font-bold text-emerald-400">{npr(card.total_price)}</span></div>
          {!cancelled && <p className="text-[11px] text-slate-500 mt-2">Payment is cash on delivery. You can change or cancel this order while it is pending.</p>}
        </Shell>
      )
    }

    case 'order_status':
      return (
        <Shell label="Order status" tone="bg-slate-900 border-slate-700/80" icon={<Package className="w-4 h-4 text-slate-400" />} title={<span className="font-mono">#{card.order_id}</span>}>
          <div className="flex justify-between items-center mb-3"><StatusPill status={card.status} /><span className="text-xs font-bold text-emerald-400">{npr(card.total_price)}</span></div>
          <ItemRows items={card.items} />
          {card.history?.length > 0 && (
            <ol className="space-y-1.5 mt-2 pt-2 border-t border-slate-800 text-xs text-slate-400" aria-label="Status timeline">
              {card.history.map((h: any, i: number) => (
                <li key={i} className="flex items-center gap-2 text-[11px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                  <span className="capitalize text-slate-200">{h.new_status}</span>
                  <span className="text-slate-500 truncate">by {h.changed_by}</span>
                </li>
              ))}
            </ol>
          )}
          {card.status === 'pending' && <p className="text-[11px] text-slate-500 mt-2">Still pending: you can change the address or items, or cancel.</p>}
        </Shell>
      )

    case 'order_list':
      return (
        <Shell label="Your orders" tone="bg-slate-900 border-slate-700/80" icon={<ListOrdered className="w-4 h-4 text-emerald-400" />} title={card.title || 'Your orders'}>
          <ul className="space-y-2">
            {card.orders.map((o: any) => (
              <li key={o.order_id} className="rounded-xl bg-slate-800/60 p-2.5 text-xs">
                <div className="flex justify-between items-center"><span className="font-mono text-white">#{o.order_id}</span><StatusPill status={o.status} /></div>
                <div className="text-slate-400 mt-1 truncate">{o.items.map((i: any) => `${i.name} × ${i.quantity}`).join(', ')}</div>
                <div className="text-right font-bold text-emerald-400 mt-0.5">{npr(o.total_price)}</div>
              </li>
            ))}
          </ul>
        </Shell>
      )

    case 'slot_picker': {
      const slots: any[] = card.slots || []
      const days = Array.from(new Set(slots.map((s) => studioDay(s.start_time))))
      return (
        <Shell label="Available time slots" tone="bg-slate-900 border-indigo-500/30" icon={<Calendar className="w-4 h-4 text-indigo-400" />} title={card.title || 'Available slots'}>
          {days.map((day) => (
            <div key={day} className="mb-3">
              {days.length > 1 && <div className="text-[11px] font-semibold text-slate-300 mb-1.5">{day}</div>}
              <div className="grid grid-cols-2 gap-2">
                {slots.filter((s) => studioDay(s.start_time) === day).map((slot, idx) => (
                  <button
                    key={`${slot.start_time}-${slot.practitioner_id}-${idx}`}
                    onClick={() => onAction && onAction(
                      `Book ${slot.service_name} (${slot.service_id}) with ${slot.practitioner_name} (${slot.practitioner_id}) on ${studioDateTime(slot.start_time)} (${slot.start_time})`)}
                    className="p-2.5 rounded-xl text-left bg-slate-800/80 hover:bg-indigo-950/60 border border-slate-700 hover:border-indigo-500/50 transition group min-h-11"
                  >
                    <div className="text-xs font-semibold text-slate-200 group-hover:text-indigo-200">{studioTime(slot.start_time)}</div>
                    <div className="text-[10px] text-slate-400 group-hover:text-slate-300 truncate">{slot.practitioner_name}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
          {card.total > slots.length && <p className="text-[11px] text-slate-500 mb-1">Showing {slots.length} of {card.total}. Ask for a different time of day to narrow it down.</p>}
          <p className="text-[10px] text-slate-400 text-center">All times are Asia/Kathmandu (UTC+05:45)</p>
        </Shell>
      )
    }

    case 'booking_summary': {
      const view = viewOf(card, proposal)
      const action = card.action || 'book'
      const tone = action === 'cancel' ? 'bg-rose-600 hover:bg-rose-500 shadow-rose-950/50' : 'bg-indigo-600 hover:bg-indigo-500 shadow-indigo-950/50'
      return (
        <Shell label="Appointment summary" tone="bg-gradient-to-br from-indigo-950/40 to-slate-900 border-indigo-500/30" icon={<Clock className="w-4 h-4 text-indigo-400" />}
          title={card.title || 'Confirm appointment'}>
          <dl className="space-y-1.5 mb-3 text-xs">
            <div className="flex justify-between gap-3"><dt className="text-slate-400">Service</dt><dd className="font-semibold text-slate-100 text-right">{card.service_name}</dd></div>
            {card.practitioner_name && <div className="flex justify-between gap-3"><dt className="text-slate-400">Practitioner</dt><dd className="text-slate-200 text-right">{card.practitioner_name}</dd></div>}
            {action === 'reschedule' && card.previous_time && <div className="flex justify-between gap-3"><dt className="text-slate-400">Currently</dt><dd className="text-slate-400 line-through text-right">{card.previous_time}</dd></div>}
            <div className="flex justify-between gap-3"><dt className="text-slate-400">{action === 'reschedule' ? 'New time' : 'When'}</dt><dd className="text-indigo-300 text-right">{card.formatted_time}</dd></div>
            {card.duration_minutes && <div className="flex justify-between gap-3"><dt className="text-slate-400">Duration</dt><dd className="text-slate-200">{card.duration_minutes} min</dd></div>}
            {action === 'cancel' ? (
              <div className="pt-2 border-t border-slate-800">
                <div className="flex justify-between text-sm"><dt className="text-slate-400">Cancellation fee</dt><dd className={`font-bold ${card.cancellation_fee > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>{card.cancellation_fee > 0 ? npr(card.cancellation_fee) : 'Free'}</dd></div>
                {card.fee_note && <p className="text-[11px] text-slate-400 mt-1">{card.fee_note}</p>}
              </div>
            ) : (
              <div className="flex justify-between pt-2 border-t border-slate-800 text-sm"><dt className="text-slate-400">Price</dt><dd className="font-bold text-teal-400">{npr(card.price)}</dd></div>
            )}
          </dl>
          <ConfirmBar card={card} view={view} busy={busy} onConfirm={onConfirm} onReject={onReject} label={card.confirm_label || 'Confirm Booking'} tone={tone} />
          <p className="text-[10px] text-slate-500 mt-2">Times are Asia/Kathmandu (UTC+05:45).</p>
        </Shell>
      )
    }

    case 'booking_confirmed':
    case 'booking_rescheduled':
    case 'booking_cancelled': {
      const cancelled = card.type === 'booking_cancelled'
      const title = card.type === 'booking_confirmed' ? 'Appointment confirmed' : cancelled ? 'Appointment cancelled' : 'Appointment rescheduled'
      return (
        <Shell label={title} tone={cancelled ? 'bg-rose-950/20 border-rose-500/30' : 'bg-teal-950/30 border-teal-500/40'}
          icon={cancelled ? <Ban className="w-4 h-4 text-rose-400" /> : <CheckCircle2 className="w-4 h-4 text-teal-400" />} title={title}>
          <div className="text-xs space-y-1 text-slate-300">
            <div>Booking <span className="font-mono font-bold text-white">#{card.booking_id}</span></div>
            <div>{card.service_name}{card.practitioner_name ? <> with <span className="text-teal-300">{card.practitioner_name}</span></> : null}</div>
            <div className="text-slate-400">{card.formatted_time || card.new_time}</div>
            {cancelled && <div className={card.cancellation_fee > 0 ? 'text-rose-300' : 'text-emerald-300'}>{card.fee_note}</div>}
            {card.price != null && !cancelled && <div className="text-teal-300 font-semibold">{npr(card.price)}</div>}
          </div>
        </Shell>
      )
    }

    case 'booking_list':
      return (
        <Shell label="Your bookings" tone="bg-slate-900 border-slate-700/80" icon={<Calendar className="w-4 h-4 text-teal-400" />} title={card.title || 'Your bookings'}>
          <ul className="space-y-2">
            {card.bookings.map((b: any) => (
              <li key={b.booking_id} className="rounded-xl bg-slate-800/60 p-2.5 text-xs">
                <div className="flex justify-between items-center gap-2"><span className="font-mono text-white">#{b.booking_id}</span><StatusPill status={b.is_past && b.status !== 'cancelled' ? 'completed' : b.status} /></div>
                <div className="text-slate-200 mt-1">{b.service_name} <span className="text-slate-400">with {b.practitioner_name}</span></div>
                <div className="text-indigo-300 mt-0.5">{studioWallClock(b.start_time)}</div>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-slate-500 mt-2">Asia/Kathmandu (UTC+05:45)</p>
        </Shell>
      )

    case 'reschedule_conflict':
      return (
        <Shell label="Reschedule conflict" tone="bg-rose-950/30 border-rose-500/40" icon={<AlertTriangle className="w-4 h-4 text-rose-400" />} title="That time is not available">
          <p className="text-xs text-rose-200/90 mb-3">{card.reason}</p>
          {(card.suggested_slots || []).length > 0 && (
            <div>
              <span className="text-[11px] font-semibold text-slate-300 block mb-2">Nearest free alternatives</span>
              <div className="space-y-1.5">
                {card.suggested_slots.map((s: any, idx: number) => (
                  <button
                    key={idx}
                    onClick={() => onAction && onAction(card.booking_id
                      ? `Move my booking ${card.booking_id} to ${studioDateTime(s.start_time)} (${s.start_time})`
                      : `Book ${s.service_name} (${s.service_id}) with ${s.practitioner_name} (${s.practitioner_id}) on ${studioDateTime(s.start_time)} (${s.start_time})`)}
                    className="w-full text-left p-2.5 rounded-lg bg-slate-900 border border-slate-800 hover:border-teal-500/50 text-xs text-slate-300 hover:text-white transition flex justify-between items-center min-h-11"
                  >
                    <span>{studioDateTime(s.start_time)} <span className="text-slate-500">with {s.practitioner_name}</span></span>
                    <ArrowRight className="w-3 h-3 text-slate-500 shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </Shell>
      )

    default:
      return null
  }
}
