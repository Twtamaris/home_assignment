import React from 'react'
import { CheckCircle2, Clock, MapPin, Calendar, AlertTriangle, ArrowRight, Package, Sparkles } from 'lucide-react'

interface RichCardProps {
  card: any
  onAction?: (actionText: string) => void
}

export const RichCard: React.FC<RichCardProps> = ({ card, onAction }) => {
  if (!card || !card.type) return null

  switch (card.type) {
    case 'order_summary':
      return (
        <div className="my-3 rounded-2xl bg-gradient-to-br from-emerald-950/40 to-slate-900 border border-emerald-500/30 p-4 shadow-lg text-slate-100 max-w-md">
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-emerald-500/20 text-emerald-400 font-semibold text-sm">
            <Package className="w-4 h-4" />
            <span>{card.title || 'Order Summary & Confirmation'}</span>
          </div>

          <div className="space-y-2 mb-3">
            {card.items?.map((item: any, idx: number) => (
              <div key={idx} className="flex justify-between items-center text-xs text-slate-300">
                <span className="font-medium text-slate-100">{item.name} <span className="text-emerald-400">× {item.quantity}</span></span>
                <span className="font-mono">NPR {item.subtotal?.toFixed(2) || (item.unit_price * item.quantity).toFixed(2)}</span>
              </div>
            ))}
          </div>

          {card.notes && card.notes.length > 0 && (
            <div className="mb-3 text-[11px] text-amber-300 bg-amber-950/30 border border-amber-500/20 rounded-lg p-2">
              {card.notes.join(' ')}
            </div>
          )}

          <div className="pt-2 border-t border-slate-800 flex justify-between items-center mb-3">
            <span className="text-xs text-slate-400">Total Payable</span>
            <span className="text-base font-bold text-emerald-400">NPR {card.total_price?.toFixed(2)}</span>
          </div>

          {card.shipping_address && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-3">
              <MapPin className="w-3.5 h-3.5 text-slate-500 shrink-0" />
              <span className="truncate">{card.shipping_address}</span>
            </div>
          )}

          <button
            onClick={() => onAction && onAction('Yes, please confirm and place my order.')}
            className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-950/50 transition flex items-center justify-center gap-2 active:scale-98"
          >
            <span>Confirm Order</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )

    case 'order_placed':
      return (
        <div className="my-3 rounded-2xl bg-emerald-950/30 border border-emerald-500/40 p-4 shadow-lg max-w-md">
          <div className="flex items-center gap-2 text-emerald-400 font-semibold text-sm mb-2">
            <CheckCircle2 className="w-4 h-4" />
            <span>Order Placed Successfully</span>
          </div>
          <div className="flex justify-between items-center text-xs mb-2">
            <span className="text-slate-400">Order ID:</span>
            <span className="font-mono font-bold text-white">{card.order_id}</span>
          </div>
          <div className="flex justify-between items-center text-xs mb-3">
            <span className="text-slate-400">Status:</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 uppercase tracking-wider border border-amber-500/30">
              {card.status}
            </span>
          </div>
          <div className="text-xs text-slate-400">
            Total: <span className="font-bold text-emerald-400">NPR {card.total_price?.toFixed(2)}</span>
          </div>
        </div>
      )

    case 'order_status':
      return (
        <div className="my-3 rounded-2xl bg-slate-900 border border-slate-700/80 p-4 shadow-lg max-w-md">
          <div className="flex justify-between items-center mb-3">
            <span className="text-xs font-mono text-slate-400">#{card.order_id}</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 uppercase tracking-wider border border-emerald-500/30">
              {card.status}
            </span>
          </div>
          {card.history && card.history.length > 0 && (
            <div className="space-y-2 mt-2 pt-2 border-t border-slate-800 text-xs text-slate-400">
              <span className="font-semibold text-slate-300 block mb-1">Status Timeline:</span>
              {card.history.map((h: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-[11px]">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  <span className="capitalize text-slate-200">{h.new_status}</span>
                  <span className="text-slate-500">by {h.changed_by}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )

    case 'slot_picker':
      return (
        <div className="my-3 rounded-2xl bg-slate-900 border border-indigo-500/30 p-4 shadow-lg text-slate-100 max-w-md">
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-indigo-500/20 text-indigo-300 font-semibold text-sm">
            <Calendar className="w-4 h-4 text-indigo-400" />
            <span>{card.title || 'Available Slots'}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
            {card.slots?.map((slot: any, idx: number) => (
              <button
                key={idx}
                onClick={() => onAction && onAction(`I want to book with ${slot.practitioner_name} at ${slot.start_time}`)}
                className="p-2.5 rounded-xl text-left bg-slate-800/80 hover:bg-indigo-950/60 border border-slate-700 hover:border-indigo-500/50 transition group"
              >
                <div className="text-xs font-semibold text-slate-200 group-hover:text-indigo-200">
                  {new Date(slot.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
                <div className="text-[10px] text-slate-400 group-hover:text-slate-300 truncate">
                  {slot.practitioner_name}
                </div>
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-400 text-center">All slots displayed in Asia/Kathmandu time (UTC+05:45)</p>
        </div>
      )

    case 'booking_summary':
      return (
        <div className="my-3 rounded-2xl bg-gradient-to-br from-indigo-950/40 to-slate-900 border border-indigo-500/30 p-4 shadow-lg text-slate-100 max-w-md">
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-indigo-500/20 text-indigo-300 font-semibold text-sm">
            <Clock className="w-4 h-4 text-indigo-400" />
            <span>Confirm Appointment</span>
          </div>
          <div className="space-y-1.5 mb-3 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400">Therapy:</span>
              <span className="font-semibold text-slate-100">{card.service_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Practitioner:</span>
              <span className="text-slate-200">{card.practitioner_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Scheduled Time:</span>
              <span className="text-indigo-300">{card.formatted_time}</span>
            </div>
            <div className="flex justify-between pt-2 border-t border-slate-800 text-sm">
              <span className="text-slate-400">Fee:</span>
              <span className="font-bold text-teal-400">NPR {card.price?.toFixed(2)}</span>
            </div>
          </div>
          <button
            onClick={() => onAction && onAction('Yes, please confirm this booking.')}
            className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-950/50 transition flex items-center justify-center gap-2 active:scale-98"
          >
            <span>Confirm Booking</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )

    case 'booking_confirmed':
      return (
        <div className="my-3 rounded-2xl bg-teal-950/30 border border-teal-500/40 p-4 shadow-lg max-w-md">
          <div className="flex items-center gap-2 text-teal-400 font-semibold text-sm mb-2">
            <CheckCircle2 className="w-4 h-4" />
            <span>Appointment Confirmed</span>
          </div>
          <div className="text-xs space-y-1 text-slate-300">
            <div>Booking ID: <span className="font-mono font-bold text-white">#{card.booking_id}</span></div>
            <div>{card.service_name} with <span className="text-teal-300">{card.practitioner_name}</span></div>
            <div className="text-slate-400">{card.formatted_time}</div>
          </div>
        </div>
      )

    case 'reschedule_conflict':
      return (
        <div className="my-3 rounded-2xl bg-rose-950/30 border border-rose-500/40 p-4 shadow-lg max-w-md">
          <div className="flex items-center gap-2 text-rose-400 font-semibold text-sm mb-2">
            <AlertTriangle className="w-4 h-4" />
            <span>Reschedule Conflict</span>
          </div>
          <p className="text-xs text-rose-200/90 mb-3">{card.reason}</p>
          {card.suggested_slots && card.suggested_slots.length > 0 && (
            <div>
              <span className="text-[11px] font-semibold text-slate-300 block mb-2">Nearest Free Alternatives:</span>
              <div className="space-y-1.5">
                {card.suggested_slots.map((s: any, idx: number) => (
                  <button
                    key={idx}
                    onClick={() => onAction && onAction(`Move my booking to ${s.start_time}`)}
                    className="w-full text-left p-2 rounded-lg bg-slate-900 border border-slate-800 hover:border-teal-500/50 text-xs text-slate-300 hover:text-white transition flex justify-between items-center"
                  >
                    <span>{s.formatted || s.start_time}</span>
                    <ArrowRight className="w-3 h-3 text-slate-500" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )

    default:
      return null
  }
}
