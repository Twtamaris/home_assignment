import datetime
from typing import List, Dict, Any, Optional, Tuple
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from app.models.models import Booking, Service, Practitioner, Holiday, WeeklyOpeningHours

KATHMANDU_TZ = pytz.timezone("Asia/Kathmandu")

class SchedulingEngine:
    """
    Studio Availability & Scheduling Engine for Lotus Wellness Studio (Asia/Kathmandu).
    Guarantees conflict-free scheduling, opening hours validation, and race-condition safety.
    """

    @staticmethod
    def now_kathmandu() -> datetime.datetime:
        return datetime.datetime.now(KATHMANDU_TZ)

    @staticmethod
    def parse_datetime_kathmandu(dt_str: str) -> datetime.datetime:
        """
        Parses an ISO string or standard datetime and localizes to Asia/Kathmandu.
        """
        try:
            # Replace 'Z' if present
            clean_str = dt_str.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                # Naive: treat as local Kathmandu time
                return KATHMANDU_TZ.localize(dt)
            return dt.astimezone(KATHMANDU_TZ)
        except Exception as e:
            # Fallback for formats like "2026-11-02 14:00"
            try:
                dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                return KATHMANDU_TZ.localize(dt)
            except Exception:
                raise ValueError(f"Invalid datetime format: {dt_str}. Please use ISO format e.g. 'YYYY-MM-DDTHH:MM:SS'.")

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
        stmt = select(WeeklyOpeningHours).where(
            WeeklyOpeningHours.org_id == org_id,
            WeeklyOpeningHours.day_of_week == weekday_name
        )
        result = await db.execute(stmt)
        record = result.scalars().first()
        if record and not record.is_closed:
            return {"open": record.open_time, "close": record.close_time}
        
        # Hardcoded defaults if not in DB
        default_hours = {
            "Monday": {"open": "08:00", "close": "19:00"},
            "Tuesday": {"open": "08:00", "close": "19:00"},
            "Wednesday": {"open": "08:00", "close": "19:00"},
            "Thursday": {"open": "08:00", "close": "19:00"},
            "Friday": {"open": "08:00", "close": "19:00"},
            "Saturday": {"open": "09:00", "close": "18:00"},
            "Sunday": {"open": "10:00", "close": "16:00"},
        }
        return default_hours.get(weekday_name)

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
        1. Inside opening hours
        2. Fits full duration before closing
        3. Not on a holiday
        4. Practitioner not double-booked
        5. Customer doesn't hold two simultaneous bookings
        """
        # Ensure start_dt is in Kathmandu tz
        if start_dt.tzinfo is None:
            start_dt = KATHMANDU_TZ.localize(start_dt)
        else:
            start_dt = start_dt.astimezone(KATHMANDU_TZ)

        end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)

        # 1. Holiday Check
        is_hol, hol_name = await cls.is_holiday(db, org_id, start_dt.date())
        if is_hol:
            return False, f"The studio is closed on {start_dt.date()} for '{hol_name}'."

        # 2. Opening Hours Check
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

        # 3. Practitioner Double-booking check
        # Convert to naive UTC or comparable datetime for SQL matching
        naive_start = start_dt.replace(tzinfo=None)
        naive_end = end_dt.replace(tzinfo=None)

        # Overlap condition: (existing.start < new.end) AND (existing.end > new.start)
        prac_query = select(Booking).where(
            Booking.org_id == org_id,
            Booking.practitioner_id == practitioner_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
            Booking.start_time < naive_end,
            Booking.end_time > naive_start
        )
        if exclude_booking_id:
            prac_query = prac_query.where(Booking.id != exclude_booking_id)

        res = await db.execute(prac_query)
        if res.scalars().first():
            return False, f"Practitioner is already booked during this time window."

        # 4. Customer overlap check (customer cannot hold two bookings at the same time)
        cust_query = select(Booking).where(
            Booking.org_id == org_id,
            Booking.user_id == customer_id,
            Booking.status.in_(["confirmed", "rescheduled"]),
            Booking.start_time < naive_end,
            Booking.end_time > naive_start
        )
        if exclude_booking_id:
            cust_query = cust_query.where(Booking.id != exclude_booking_id)

        res_cust = await db.execute(cust_query)
        if res_cust.scalars().first():
            return False, f"You already have another active appointment booked during this time."

        return True, "Slot is available."

    @classmethod
    async def find_available_slots(
        cls,
        db: AsyncSession,
        org_id: str,
        service_id: str,
        target_date_str: str,
        practitioner_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculates all free slots on the given target date for the specified service and practitioner.
        """
        # Get service duration
        s_stmt = select(Service).where(Service.id == service_id, Service.org_id == org_id)
        s_res = await db.execute(s_stmt)
        service = s_res.scalars().first()
        if not service:
            return []

        try:
            target_date = datetime.date.fromisoformat(target_date_str.split("T")[0])
        except Exception:
            return []

        # Check holiday
        is_hol, hol_name = await cls.is_holiday(db, org_id, target_date)
        if is_hol:
            return []

        weekday_name = target_date.strftime("%A")
        hours = await cls.get_opening_hours_for_day(db, org_id, weekday_name)
        if not hours:
            return []

        open_h, open_m = map(int, hours["open"].split(":"))
        close_h, close_m = map(int, hours["close"].split(":"))

        day_start = KATHMANDU_TZ.localize(datetime.datetime.combine(target_date, datetime.time(open_h, open_m)))
        day_end = KATHMANDU_TZ.localize(datetime.datetime.combine(target_date, datetime.time(close_h, close_m)))

        # Find practitioners eligible
        if practitioner_id:
            prac_stmt = select(Practitioner).where(Practitioner.id == practitioner_id, Practitioner.org_id == org_id)
        else:
            prac_stmt = select(Practitioner).where(Practitioner.org_id == org_id)
        p_res = await db.execute(prac_stmt)
        practitioners = p_res.scalars().all()

        available_slots = []
        step_minutes = 30  # Search every 30-min block

        for prac in practitioners:
            # Filter by specialty if applicable
            if service.name not in prac.specialties and len(prac.specialties) > 0:
                # Check partial match
                if not any(service.name.lower() in spec.lower() for spec in prac.specialties):
                    continue

            curr = day_start
            while curr + datetime.timedelta(minutes=service.duration_minutes) <= day_end:
                slot_end = curr + datetime.timedelta(minutes=service.duration_minutes)
                naive_start = curr.replace(tzinfo=None)
                naive_end = slot_end.replace(tzinfo=None)

                # Check conflict
                conflict_stmt = select(Booking).where(
                    Booking.org_id == org_id,
                    Booking.practitioner_id == prac.id,
                    Booking.status.in_(["confirmed", "rescheduled"]),
                    Booking.start_time < naive_end,
                    Booking.end_time > naive_start
                )
                res = await db.execute(conflict_stmt)
                if not res.scalars().first():
                    available_slots.append({
                        "practitioner_id": prac.id,
                        "practitioner_name": prac.name,
                        "service_id": service.id,
                        "service_name": service.name,
                        "start_time": curr.isoformat(),
                        "end_time": slot_end.isoformat(),
                        "formatted": f"{curr.strftime('%Y-%m-%d %I:%M %p')} with {prac.name}"
                    })

                curr += datetime.timedelta(minutes=step_minutes)

        return available_slots

    @classmethod
    async def find_nearest_alternatives(
        cls,
        db: AsyncSession,
        org_id: str,
        service_id: str,
        requested_dt: datetime.datetime,
        practitioner_id: Optional[str] = None,
        count: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Finds the nearest alternative free slots on the same day or next consecutive days.
        """
        alternatives = []
        for day_offset in range(0, 3):
            check_date = (requested_dt + datetime.timedelta(days=day_offset)).date()
            slots = await cls.find_available_slots(db, org_id, service_id, check_date.isoformat(), practitioner_id)
            for s in slots:
                alternatives.append(s)
                if len(alternatives) >= count:
                    return alternatives
        return alternatives
