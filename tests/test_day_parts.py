"""day_parts — the two plain labels behind the message day rule."""
from datetime import datetime, timedelta

from iphonebridge.ui.util import day_parts, daystamp


def _stamp(days_ago: int) -> str:
    return (datetime.now().astimezone()
            - timedelta(days=days_ago)).replace(hour=15, minute=54
                                                ).isoformat()


def test_today_and_yesterday():
    assert day_parts(_stamp(0)) == ("Today", "15:54")
    assert day_parts(_stamp(1)) == ("Yesterday", "15:54")


def test_weekday_and_older():
    day, time = day_parts(_stamp(3))
    assert day in ("Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday")
    assert time == "15:54"
    day, _ = day_parts(_stamp(30))
    assert any(m in day for m in ("Jan", "Feb", "Mar", "Apr", "May",
                                  "Jun", "Jul", "Aug", "Sep", "Oct",
                                  "Nov", "Dec"))


def test_unparsable():
    assert day_parts(None) == ("", "")
    assert day_parts("not a date") == ("", "")


def test_daystamp_still_agrees():
    day, time = day_parts(_stamp(1))
    assert daystamp(_stamp(1)) == f"<b>{day}</b>  {time}"
    assert daystamp(None) == ""
