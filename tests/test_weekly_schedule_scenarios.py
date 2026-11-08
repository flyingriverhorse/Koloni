"""Slice 67's acceptance set, part 2: a schedule on chosen days of the week. Written before the code.

The user, 21 Oct: the "check the dependencies" card should be "every Friday", and the schedule
could not say a day ("bence bunu da düzeltmek lazım"). A schedule `{"at": "HH:MM", "days": ...}`
takes, besides "daily" and "weekdays", a list of days: ["mon", "tue", "wed", "thu", "fri", "sat",
"sun"] (at least one, no repeats; kept in week order). It is due at that time on those days only.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app import triggers

try:
    triggers.check_config("schedule", {"at": "17:00", "days": ["fri"]})
except triggers.Invalid:
    pytest.skip("slice 67's weekly schedule is not built yet", allow_module_level=True)

ZONE = timezone(timedelta(hours=3))  # Istanbul, no clock change


def test_days_of_the_week_are_kept_in_week_order():
    said = triggers.check_config("schedule", {"at": "09:30", "days": ["fri", "mon"]})
    assert said == {"at": "09:30", "days": ["mon", "fri"]}


@pytest.mark.parametrize("days", [[], ["fri", "fri"], ["friday"], "fri", [5]])
def test_a_day_list_must_name_real_days_once(days):
    with pytest.raises(triggers.Invalid):
        triggers.check_config("schedule", {"at": "09:30", "days": days})


def test_the_old_forms_still_hold():
    assert triggers.check_config("schedule", {"at": "09:30", "days": "weekdays"})["days"] == "weekdays"
    assert triggers.check_config("schedule", {"at": "09:30"})["days"] == "daily"


def test_it_is_due_on_the_next_chosen_day_only():
    # Tuesday 21 Oct 2026, 10:00 local.
    after = datetime(2026, 10, 21, 7, 0, tzinfo=UTC)
    due = triggers.next_time("17:00", ["fri"], after, ZONE)
    local = due.astimezone(ZONE)
    assert (local.weekday(), local.hour, local.minute) == (4, 17, 0)
    assert local.date().isoformat() == "2026-10-23"


def test_a_chosen_day_that_is_today_and_still_ahead_is_today():
    after = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)  # Friday 10:00 local
    assert triggers.next_time("17:00", ["fri"], after, ZONE).astimezone(ZONE).date().isoformat() == "2026-10-23"


def test_past_today_it_is_a_week_later():
    after = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)  # Friday 18:00 local
    assert triggers.next_time("17:00", ["fri"], after, ZONE).astimezone(ZONE).date().isoformat() == "2026-10-30"


def test_it_is_said_in_words():
    assert triggers.when_in_words("schedule", {"at": "17:00", "days": ["fri"]}) == "Fridays at 17:00"
    assert triggers.when_in_words("schedule", {"at": "09:00", "days": ["mon", "thu"]}) == (
        "Mondays and Thursdays at 09:00")
