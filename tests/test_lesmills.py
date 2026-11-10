from app import lesmills


def card(date, time, name, mins=30, who="Glen Ostergaard", studio="Cycle Studio", second=""):
    return {"startDate": date, "startTime": time, "className": name, "durationMins": mins,
            "mainInstructorName": who, "secondaryInstructorName": second, "siteName": studio}


def test_picks_the_710_cycle_class_on_tuesday_and_thursday():
    cards = [
        card("10 Nov 2026", "07:10", "SPRINT"),
        card("10 Nov 2026", "06:10", "RPM", 45, "Tommi Wong "),
        card("10 Nov 2026", "07:10", "VIRTUAL SPRINT"),          # virtual classes are ignored
        card("10 Nov 2026", "07:05", "GRIT STRENGTH"),           # not a cycle class
        card("11 Nov 2026", "07:10", "THE TRIP", 45),            # Wednesday: not a Les Mills day in the plan
        card("12 Nov 2026", "07:10", "THE TRIP", 45, "Chris Richardson"),
        card("12 Nov 2026", "07:10", "RPM", 45, "Someone Else"), # RPM is preferred over The Trip
    ]
    days = lesmills.pick_classes(cards, "07:10")
    assert sorted(days) == ["2026-11-10", "2026-11-12"]
    tue = days["2026-11-10"]
    assert tue == {"time": "7:10–7:40 AM", "name": "Les Mills Sprint", "mins": 30, "studio": "Cycle Studio",
                   "instructor": "Glen Ostergaard", "alt": "RPM at 6:10 AM (45 min) with Tommi Wong, Cycle Studio"}
    assert days["2026-11-12"]["name"] == "RPM" and "alt" not in days["2026-11-12"]


def test_no_class_at_that_time_means_no_entry():
    assert lesmills.pick_classes([card("10 Nov 2026", "09:30", "THE TRIP", 45)], "07:10") == {}
    assert lesmills.pick_classes([{"className": "SPRINT", "startDate": "not a date", "startTime": "07:10"}], "07:10") == {}


def test_time_spans():
    assert lesmills._span("07:10", 30) == "7:10–7:40 AM"
    assert lesmills._span("11:40", 45) == "11:40 AM–12:25 PM"
    assert lesmills._span("12:10", 45) == "12:10–12:55 PM"
