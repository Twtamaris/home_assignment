import datetime
import asyncio
import re
from typing import List, Dict, Any, Optional, Tuple
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.models import Booking, Service, Practitioner, Holiday, WeeklyOpeningHours

KATHMANDU_TZ = pytz.timezone("Asia/Kathmandu")

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ACTIVE_STATUSES = ["confirmed", "rescheduled"]
SLOT_STEP_MINUTES = 30

# Used only when an organisation has no weekly_opening_hours rows at all.
_DEFAULT_HOURS = {
    "Monday": {"open": "08:00", "close": "19:00"},
    "Tuesday": {"open": "08:00", "close": "19:00"},
    "Wednesday": {"open": "08:00", "close": "19:00"},
    "Thursday": {"open": "08:00", "close": "19:00"},
    "Friday": {"open": "08:00", "close": "19:00"},
    "Saturday": {"open": "09:00", "close": "18:00"},
    "Sunday": {"open": "10:00", "close": "16:00"},
}

PARTS_OF_DAY = {
    "morning": (0, 12),
    "afternoon": (12, 17),
    "evening": (17, 24),
}


class SchedulingEngine:
    """
    Studio Availability & Scheduling Engine for Lotus Wellness Studio (Asia/Kathmandu).
    Guarantees conflict-free scheduling, opening hours validation, and race-condition safety.
    """
    booking_lock = asyncio.Lock()

    @staticmethod
    def now_kathmandu() -> datetime.datetime:
        return datetime.datetime.now(KATHMANDU_TZ)

    @classmethod
    def resolve_relative_datetime_kathmandu(
        cls, expr: str, ref_dt: Optional[datetime.datetime] = None
    ) -> datetime.datetime:
        """
        Rule 6: Resolves natural language relative dates e.g. 'next Tuesday afternoon', 'tomorrow morning'
        anchored to Asia/Kathmandu (UTC+05:45). Raises ValueError when no date is recognised.
        """
        now = ref_dt or cls.now_kathmandu()
        text = expr.lower().strip()
        today = now.date()

        target_date = None
        if re.search(r"\bday after tomorrow\b", text):
            target_date = today + datetime.timedelta(days=2)
        elif re.search(r"\b(tomorrow|tmrw)\b", text):
            target_date = today + datetime.timedelta(days=1)
        elif re.search(r"\b(today|tonight)\b", text):
            target_date = today
        else:
            in_days = re.search(r"\bin (\d{1,2}) days?\b", text)
            if in_days:
                target_date = today + datetime.timedelta(days=int(in_days.group(1)))
            else:
                for index, day in enumerate(_WEEKDAYS):
                    if re.search(rf"\b{day}\b", text):
                        days_ahead = (index - now.weekday()) % 7
                        if days_ahead == 0:
                            days_ahead = 7
                        target_date = today + datetime.timedelta(days=days_ahead)
                        break
                if target_date is None and re.search(r"\bnext week\b", text):
                    target_date = today + datetime.timedelta(days=7)
        if target_date is None:
            iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
            if iso:
                target_date = datetime.date.fromisoformat(iso.group(1))
        if target_date is None:
            raise ValueError(f"Could not work out a date from '{expr}'.")

        hour, minute = 10, 0
        if re.search(r"\bafternoon\b", text):
            hour = 14
        elif re.search(r"\bmorning\b", text):
            hour = 10
        elif re.search(r"\b(evening|tonight)\b", text):
            hour = 17
        elif re.search(r"\bnoon\b", text):
            hour = 12

        clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text) or re.search(r"\b(\d{1,2}):(\d{2})()\b", text)
        if clock:
            hour = int(clock.group(1))
            minute = int(clock.group(2) or 0)
            meridiem = clock.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Could not work out a time from '{expr}'.")

        return KATHMANDU_TZ.localize(datetime.datetime.combine(target_date, datetime.time(hour, minute)))

    @classmethod
    def parse_datetime_kathmandu(cls, dt_str: str) -> datetime.datetime:
        """
        Parses an ISO string or a relative phrase and localizes to Asia/Kathmandu.
        """
        raw = (dt_str or "").strip()
        try:
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return KATHMANDU_TZ.localize(dt)
            return dt.astimezone(KATHMANDU_TZ)
        except ValueError:
            pass
        try:
            return KATHMANDU_TZ.localize(datetime.datetime.strptime(raw, "%Y-%m-%d %H:%M"))
        except ValueError:
            pass
        try:
            return cls.resolve_relative_datetime_kathmandu(raw)
        except ValueError:
            raise ValueError(
                f"Invalid datetime format: {dt_str}. Please use ISO format e.g. 'YYYY-MM-DDTHH:MM:SS'."
            )

    @staticmethod
    def practitioner_offers(practitioner: Practitioner, service: Service) -> bool:
        """A practitioner with a specialties list only performs the services on it."""
        specialties = practitioner.specialties
        if not specialties:
            return True
        name = service.name.lower()
        return service.name in specialties or any(name in spec.lower() for spec in specialties)

    @classmethod
    def _localize(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None:
            return KATHMANDU_TZ.localize(value)
        return value.astimezone(KATHMANDU_TZ)

    @classmethod
    async def is_holiday(cls, db: AsyncSession, org_id: str, target_date: datetime.date) -> Tuple[bool, Optional[str]]:
        date_str = target_date.strftime("%Y-%m-%d")
        stmt = select(Holiday).where(Holiday.org_id == org_id, Holiday.holiday_date == date_str)
        result = await db.execute(stmt)
        holiday = result.scalars().first()
        if holiday:
            return True, holiday.name
        return False, None

    @classmethod
    async def get_opening_hours_for_day(cls, db: AsyncSession, org_id: str, weekday_name: str) -> Optional[Dict[str, str]]:
        """Hours for one weekday, or None when the studio is closed that day."""
        stmt = select(WeeklyOpeningHours).where(
            WeeklyOpeningHours.org_id == org_id,
            WeeklyOpeningHours.day_of_week == weekday_name
        )
        record = (await db.execute(stmt)).scalars().first()
        if record is not None:
            # A stored row is authoritative, including is_closed.
            if record.is_closed:
                return None
            return {"open": record.open_time, "close": record.close_time}

        any_hours = (await db.execute(
            select(WeeklyOpeningHours.id).where(WeeklyOpeningHours.org_id == org_id).limit(1)
        )).first()
        if any_hours is not None:
            # The org defines its own week and has no row for this day: closed.
            return None
        return _DEFAULT_HOURS.get(weekday_name)

    @classmethod
    async def validate_slot(
        cls,
        db: AsyncSession,
        org_id: str,
        start_dt: datetime.datetime,
        duration_minutes: int,
        practitioner_id: str,
        customer_id: str,
        exclude_booking_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Validates:
        0. Not in the past
        1. Not on a holiday
        2. Inside opening hours and fits the full duration before closing
        3. Practitioner not double-booked
        4. Customer doesn't hold two simultaneous bookings
        """
        start_dt = cls._localize(start_dt)
        end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

        if start_dt <= cls.now_kathmandu():
            return False, (
                f"{start_dt.strftime('%A, %b %d at %I:%M %p')} has already passed "
                "(studio time is Asia/Kathmandu)."
            )

        is_hol, hol_name = await cls.is_holiday(db, org_id, start_dt.date())
        if is_hol:
            return False, f"The studio is closed on {start_dt.date()} for '{hol_name}'."

        weekday_name = start_dt.strftime("%A")
        hours = await cls.get_opening_hours_for_day(db, org_id, weekday_name)
        if not hours:
            return False, f"The studio is closed on {weekday_name}s."

        open_hour, open_min = map(int, hours["open"].split(":"))
        close_hour, close_min = map(int, hours["close"].split(":"))

        day_open = start_dt.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)
        day_close = start_dt.replace(hour=close_hour, minute=close_min, second=0, microsecond=0)

        if start_dt < day_open or end_dt > day_close:
            return False, (
                f"Requested slot ({start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}) "
                f"falls outside {weekday_name} opening hours ({hours['open']} - {hours['close']})."
            )

        # Bookings are stored as naive Asia/Kathmandu wall-clock time.
        naive_start = start_dt.replace(tzinfo=None)
        naive_end = end_dt.replace(tzinfo=None)

        # Overlap condition: (existing.start < new.end) AND (existing.end > new.start)
        prac_query = select(Booking).where(
            Booking.org_id == org_id,
            Booking.practitioner_id == practitioner_id,
            Booking.status.in_(_ACTIVE_STATUSES),
            Booking.start_time < naive_end,
            Booking.end_time > naive_start
        )
        if exclude_booking_id:
            prac_query = prac_query.where(Booking.id != exclude_booking_id)

        res = await db.execute(prac_query)
        if res.scalars().first():
            return False, "Practitioner is already booked during this time window (booked by another customer)."

        cust_query = select(Booking).where(
            Booking.org_id == org_id,
            Booking.user_id == customer_id,
            Booking.status.in_(_ACTIVE_STATUSES),
            Booking.start_time < naive_end,
            Booking.end_time > naive_start
        )
        if exclude_booking_id:
            cust_query = cust_query.where(Booking.id != exclude_booking_id)

        res_cust = await db.execute(cust_query)
        if res_cust.scalars().first():
            return False, "You already have another active appointment booked during this time."

        return True, "Slot is available."

    @classmethod
    async def find_available_slots(
        cls,
        db: AsyncSession,
        org_id: str,
        service_id: str,
        target_date_str: str,
        practitioner_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        exclude_booking_id: Optional[str] = None,
        part_of_day: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Free slots on the given date for the service, optionally limited to one practitioner,
        one part of the day, and (when customer_id is given) times the customer is not already busy.
        Past times are never offered.
        """
        service = (await db.execute(
            select(Service).where(Service.id == service_id, Service.org_id == org_id)
        )).scalars().first()
        if not service:
            return []

        try:
            target_date = datetime.date.fromisoformat(target_date_str.split("T")[0])
        except Exception:
            return []

        is_hol, _ = await cls.is_holiday(db, org_id, target_date)
        if is_hol:
            return []

        hours = await cls.get_opening_hours_for_day(db, org_id, target_date.strftime("%A"))
        if not hours:
            return []

        open_h, open_m = map(int, hours["open"].split(":"))
        close_h, close_m = map(int, hours["close"].split(":"))
        day_start = KATHMANDU_TZ.localize(datetime.datetime.combine(target_date, datetime.time(open_h, open_m)))
        day_end = KATHMANDU_TZ.localize(datetime.datetime.combine(target_date, datetime.time(close_h, close_m)))

        prac_stmt = select(Practitioner).where(Practitioner.org_id == org_id)
        if practitioner_id:
            prac_stmt = prac_stmt.where(Practitioner.id == practitioner_id)
        practitioners = (await db.execute(prac_stmt)).scalars().all()

        # One query for the whole day instead of one per candidate slot.
        window_start = day_start.replace(tzinfo=None)
        window_end = day_end.replace(tzinfo=None)
        busy_rows = (await db.execute(
            select(Booking).where(
                Booking.org_id == org_id,
                Booking.status.in_(_ACTIVE_STATUSES),
                Booking.start_time < window_end,
                Booking.end_time > window_start,
            )
        )).scalars().all()
        if exclude_booking_id:
            busy_rows = [row for row in busy_rows if row.id != exclude_booking_id]

        hour_range = PARTS_OF_DAY.get((part_of_day or "").lower())
        now = cls.now_kathmandu()
        duration = datetime.timedelta(minutes=service.duration_minutes)
        available_slots: List[Dict[str, Any]] = []

        for prac in practitioners:
            if not cls.practitioner_offers(prac, service):
                continue
            prac_busy = [row for row in busy_rows if row.practitioner_id == prac.id]
            customer_busy = [row for row in busy_rows if customer_id and row.user_id == customer_id]

            curr = day_start
            while curr + duration <= day_end:
                slot_end = curr + duration
                naive_start = curr.replace(tzinfo=None)
                naive_end = slot_end.replace(tzinfo=None)
                in_part = hour_range is None or hour_range[0] <= curr.hour < hour_range[1]
                if (
                    curr > now
                    and in_part
                    and not any(row.start_time < naive_end and row.end_time > naive_start for row in prac_busy)
                    and not any(row.start_time < naive_end and row.end_time > naive_start for row in customer_busy)
                ):
                    available_slots.append({
                        "practitioner_id": prac.id,
                        "practitioner_name": prac.name,
                        "service_id": service.id,
                        "service_name": service.name,
                        "start_time": curr.isoformat(),
                        "end_time": slot_end.isoformat(),
                        "formatted": f"{curr.strftime('%a %Y-%m-%d %I:%M %p')} with {prac.name}"
                    })
                curr += datetime.timedelta(minutes=SLOT_STEP_MINUTES)

        available_slots.sort(key=lambda slot: (slot["start_time"], slot["practitioner_name"]))
        return available_slots

    @classmethod
    async def find_nearest_alternatives(
        cls,
        db: AsyncSession,
        org_id: str,
        service_id: str,
        requested_dt: datetime.datetime,
        practitioner_id: Optional[str] = None,
        count: int = 3,
        customer_id: Optional[str] = None,
        exclude_booking_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        The free slots closest in time to the requested one, looking one day back and
        three days forward. Sorted by distance from the request, then returned in time order.
        """
        requested = cls._localize(requested_dt)
        candidates: List[Dict[str, Any]] = []
        for day_offset in range(-1, 4):
            check_date = (requested + datetime.timedelta(days=day_offset)).date()
            candidates.extend(await cls.find_available_slots(
                db, org_id, service_id, check_date.isoformat(), practitioner_id,
                customer_id=customer_id, exclude_booking_id=exclude_booking_id,
            ))

        def distance(slot: Dict[str, Any]) -> float:
            return abs((datetime.datetime.fromisoformat(slot["start_time"]) - requested).total_seconds())

        nearest = sorted(candidates, key=distance)[:count]
        return sorted(nearest, key=lambda slot: slot["start_time"])
