"""
timing.py - everything about clock times.

All times are stored as text in the form 'YYYY-MM-DD HH:MM' (for example
'2026-11-20 14:35'). That is easy to read in the database and easy to sort.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Break between two batches, used to re-organise the courts.
PAUSE_MINUTES = 3

# The clock of the server can be in another time zone (servers often use UTC),
# so we always ask for the time in Leiden. Can be changed with the TIMEZONE
# environment variable.
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Amsterdam")

TIME_FORMAT = "%Y-%m-%d %H:%M"


def now_text():
    """The current local time as text, e.g. '2026-11-20 14:35'."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    return now.strftime(TIME_FORMAT)


def text_to_time(text):
    """'2026-11-20 14:35' -> a datetime object."""
    return datetime.strptime(text, TIME_FORMAT)


def time_to_text(moment):
    """A datetime object -> '2026-11-20 14:35'."""
    return moment.strftime(TIME_FORMAT)


def add_minutes(text, minutes):
    """'2026-11-20 14:35' + 20 minutes -> '2026-11-20 14:55'."""
    return time_to_text(text_to_time(text) + timedelta(minutes=minutes))


def minutes_between(earlier_text, later_text):
    """How many minutes from earlier_text to later_text (negative if it is earlier)."""
    difference = text_to_time(later_text) - text_to_time(earlier_text)
    return int(difference.total_seconds() // 60)


def schedule_minutes(game_minutes, number_of_batches):
    """How long a schedule takes from the first start to the last game's end."""
    if number_of_batches <= 0:
        return 0
    return number_of_batches * game_minutes + (number_of_batches - 1) * PAUSE_MINUTES


def clock(text):
    """'2026-11-20 14:35' -> '14:35' (only the hours and minutes)."""
    if not text:
        return "--:--"
    return text[11:16]


def calculate_game_minutes(total_minutes, number_of_batches):
    """
    How long one game may take.

    total time = batches x game time + (batches - 1) x pause
    so: game time = (total time - (batches - 1) x pause) / batches

    The answer is rounded down to whole minutes (and is at least 1).
    """
    if number_of_batches <= 0:
        return total_minutes
    playing_time = total_minutes - PAUSE_MINUTES * (number_of_batches - 1)
    minutes = playing_time // number_of_batches
    if minutes < 1:
        minutes = 1
    return minutes


def calculate_batch_start_times(start_time, game_minutes, number_of_batches, real_start_times):
    """
    Estimated start time of every batch.

    start_time        : datetime when the START button was pressed
    game_minutes      : planned length of one game
    number_of_batches : how many batches there are
    real_start_times  : dictionary batch -> datetime, filled in by managers with
                        "Update time". A real time always wins over the estimate,
                        and the batches after it are calculated from it.

    Returns a dictionary batch -> datetime.
    """
    one_slot = timedelta(minutes=game_minutes + PAUSE_MINUTES)
    times = {}
    for batch in range(1, number_of_batches + 1):
        if batch in real_start_times:
            times[batch] = real_start_times[batch]
        elif batch == 1:
            times[batch] = start_time
        else:
            times[batch] = times[batch - 1] + one_slot
    return times
