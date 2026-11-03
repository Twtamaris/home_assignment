/** The studio runs on Asia/Kathmandu (UTC+05:45). Every time shown to a customer is in that zone. */
export const STUDIO_TZ = 'Asia/Kathmandu'

const WITH_ZONE = /(Z|[+-]\d{2}:?\d{2})$/

/** A timestamp with an offset ("2026-11-10T15:00:00+05:45") as studio time: "Tue 10 Nov, 3:00 PM". */
export function studioDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: STUDIO_TZ, weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(date)
}

export function studioTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-GB', { timeZone: STUDIO_TZ, hour: 'numeric', minute: '2-digit', hour12: true }).format(date)
}

export function studioDay(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('en-GB', { timeZone: STUDIO_TZ, weekday: 'long', day: 'numeric', month: 'long' }).format(date)
}

/**
 * Booking times are stored as studio wall-clock time without an offset ("2026-11-10T15:00:00").
 * They are shown as written, never shifted into the browser's zone.
 */
export function studioWallClock(naive: string): string {
  if (WITH_ZONE.test(naive)) return studioDateTime(naive)
  const date = new Date(`${naive}Z`)
  if (Number.isNaN(date.getTime())) return naive
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
  }).format(date)
}

/** The server sends naive UTC for created_at and expires_at. */
export function parseServerUtc(value: string): Date {
  return new Date(WITH_ZONE.test(value) ? value : `${value}Z`)
}

export function npr(value: number | undefined | null): string {
  return `NPR ${Number(value ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** True when a studio wall-clock time ("2026-11-10T15:00:00", no offset) has already passed in Kathmandu. */
export function isPastStudioTime(naive: string): boolean {
  const iso = WITH_ZONE.test(naive) ? naive : `${naive}+05:45`
  const when = new Date(iso).getTime()
  return !Number.isNaN(when) && when <= Date.now()
}
