"""
Reads the operator-maintained press schedule workbooks (one .xls per
shift, on a network share) to answer: given what's actually running at
the press right now, how many billets remain before the alloy changes?

The PLC's own "Scheduled Billets" field isn't reliable -- the real
schedule lives in these workbooks. Layout is consistent across every
shift file (confirmed against two real files):

    col 0  Die #            col 9  blt length
    col 1  Suffix (=DieCopy) col 10 blts ran (updated near job-end, not live)
    col 2  Job #             col 16 Comments
    col 3  Part #  (or "ALLOY CHANGE to X" marker text)
    col 4  Alloy/temper
    col 5  # blts (scheduled)

Row 1 is the header row; job rows start at row 2. A row counts as a
job row if it has a Job # (col 2); a row whose Part # (col 3) starts
with "ALLOY CHANGE" is a boundary marker, not a job.
"""

from datetime import datetime, timedelta
import os
import xlrd

# UNC path, not a drive letter -- "Y:" is a per-machine mapping that isn't
# guaranteed to exist (confirmed: it doesn't on the collector's actual PC),
# whereas this resolves the same way from any machine with network access
# to the file server.
SCHEDULE_DIR = "//lud-storage.whitehallindustries.com/PADUCAH - Press & Production/PADUCAH - Press Schedules/PRESS REPORTS"

SHIFT_1ST = "1st"
SHIFT_2ND = "2nd"
SHIFT_3RD = "3rd"

SHIFT_ORDER = [SHIFT_1ST, SHIFT_2ND, SHIFT_3RD]  # chronological order within a shift-date

COL_DIE = 0
COL_SUFFIX = 1
COL_JOB = 2
COL_PART = 3
COL_ALLOY = 4
COL_SCHEDULED_BILLETS = 5
COL_BILLET_LENGTH = 9
COL_BILLETS_RAN = 10
COL_DIE_TEMP = 11
COL_START_TIME = 12
COL_STOP_TIME = 13


def get_shift_info(dt):
    """
    Returns (shift_date, shift_name) for the shift containing dt.
    3rd shift runs 11pm-7am and is dated to the day it STARTED (e.g. 2am
    Saturday is still "Friday's 3rd shift") -- confirmed against real
    workbook DATE cells, which showed Friday's date on both the "Friday
    3rd Shift" and "Friday 1st Shift" files.
    """

    hour = dt.hour

    if 7 <= hour < 15:
        return dt.date(), SHIFT_1ST

    if 15 <= hour < 23:
        return dt.date(), SHIFT_2ND

    shift_date = dt.date() if hour >= 23 else dt.date() - timedelta(days=1)
    return shift_date, SHIFT_3RD


def get_next_shift_info(shift_date, shift_name):
    """The (date, name) of the shift immediately following the given one."""

    idx = SHIFT_ORDER.index(shift_name)

    if idx == len(SHIFT_ORDER) - 1:
        return shift_date + timedelta(days=1), SHIFT_ORDER[0]

    return shift_date, SHIFT_ORDER[idx + 1]


def find_shift_file(shift_date, shift_name):
    """
    Scans SCHEDULE_DIR for the workbook matching this shift, rather than
    constructing an exact filename -- the Letter-Number prefix scheme
    (e.g. "A-2 Press Report - ...") isn't fully reliable (confirmed: an
    old templates folder had the same day/shift using a different number),
    but every file we've seen still embeds the weekday name and shift
    ordinal as plain text, which is what's matched on here instead.
    Raises FileNotFoundError (same as a direct open would) if the
    directory itself isn't reachable or nothing matches, so callers don't
    need to handle a new failure mode.
    """

    weekday_name = shift_date.strftime("%A").lower()
    shift_lower = shift_name.lower()

    try:
        all_files = os.listdir(SCHEDULE_DIR)
    except OSError as e:
        raise FileNotFoundError(f"Schedule directory not reachable: {SCHEDULE_DIR} ({e})") from e

    candidates = sorted(
        f for f in all_files
        if f.lower().endswith(".xls")
        and weekday_name in f.lower()
        and shift_lower in f.lower()
    )

    if not candidates:
        raise FileNotFoundError(
            f"No schedule file found for {shift_date} {shift_name} shift in {SCHEDULE_DIR} "
            f"(looked for a .xls file containing {weekday_name!r} and {shift_lower!r})"
        )

    # if more than one file matches (e.g. a stray "Copy of ..."), prefer the
    # shortest name -- the plain, non-copy filename is virtually always shorter
    candidates.sort(key=len)
    return f"{SCHEDULE_DIR}/{candidates[0]}"


def parse_schedule(path):
    """
    Returns an ordered list of entries from a shift workbook: job dicts
    and {"alloyChange": "<new alloy>"} marker dicts, in row order.
    """

    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)

    entries = []

    for row in range(2, sheet.nrows):
        part = sheet.cell_value(row, COL_PART)

        if isinstance(part, str) and part.strip().upper().startswith("ALLOY CHANGE"):
            entries.append({"alloyChange": part.strip()})
            continue

        job = sheet.cell_value(row, COL_JOB)
        if not job:
            continue

        entries.append({
            "die": sheet.cell_value(row, COL_DIE),
            "suffix": sheet.cell_value(row, COL_SUFFIX),
            "job": int(job),
            "part": sheet.cell_value(row, COL_PART),
            "alloy": sheet.cell_value(row, COL_ALLOY),
            "scheduledBillets": sheet.cell_value(row, COL_SCHEDULED_BILLETS),
            "billetLength": sheet.cell_value(row, COL_BILLET_LENGTH),
            "billetsRan": sheet.cell_value(row, COL_BILLETS_RAN),
            "dieTemp": sheet.cell_value(row, COL_DIE_TEMP),
            "startTime": sheet.cell_value(row, COL_START_TIME),
            "stopTime": sheet.cell_value(row, COL_STOP_TIME),
        })

    return entries


def _to_int(value):
    """Safe numeric coercion for matching PLC fields against workbook cells --
    either side can be an int, a float, a numeric string, or a blank string."""

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_filled(value):
    return value not in (None, "", 0)


def _day_fraction(dt):
    """Time-of-day as a 0-1 fraction, matching how Excel stores the Start/Stop cells."""
    return (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400


def _has_really_stopped(stop_time, now_fraction):
    """
    A Stop time only counts as real evidence of completion if it's already
    in the past. Operators sometimes pencil in an optimistic stop time
    ahead of time (e.g. "I'll be on this die the rest of my shift") before
    the job has actually finished -- confirmed live: a Stop time ~50
    minutes in the future on a job that was, per the operator, still
    running. A future Stop time is a plan, not a fact.
    """

    return _is_filled(stop_time) and stop_time <= now_fraction


def _find_current_index(entries, current_profile, current_die_copy, now):
    """
    Finds which job row is actually running right now. Job Number (#) isn't
    used -- it's manual operator input in the PLC/HMI and isn't reliably
    kept up to date. Profile+Die Copy (automatically reflecting whatever
    die is physically mounted) is matched against the workbook's Die #.

    Die # alone isn't always unique (the same die can run multiple jobs
    back to back, sometimes with Suffix filled in to disambiguate,
    sometimes not, and scheduled jobs are sometimes informally consolidated
    on the operator floor without the schedule being updated to reflect
    it). So: narrow by Suffix when it actually disambiguates, then break
    any remaining tie using operator-entered progress -- a row with a
    Start time and no Stop time that's already passed is the one actually
    in progress right now, even if earlier rows in the list look like they
    got skipped over. If that still doesn't land on exactly one row, this
    returns None rather than guess.
    """

    die_matches = [
        i for i, e in enumerate(entries)
        if "job" in e and _to_int(e["die"]) == current_profile
    ]

    if not die_matches:
        return None

    suffix_matches = [
        i for i in die_matches
        if _to_int(entries[i]["suffix"]) == current_die_copy
    ]

    candidates = suffix_matches or die_matches

    now_fraction = _day_fraction(now)

    in_progress = [
        i for i in candidates
        if _is_filled(entries[i]["startTime"])
        and not _has_really_stopped(entries[i]["stopTime"], now_fraction)
    ]

    if len(in_progress) == 1:
        return in_progress[0]

    return None  # ambiguous or no in-progress row -- skip rather than guess


def predict_billets_until_alloy_change(
    current_profile, current_die_copy, current_billet_number, current_scheduled_billets, now=None
):
    """
    current_profile: the live "Profile" field from press_data (matches the
        workbook's Die #).
    current_die_copy: the live "Die Copy" field from press_data (matches
        the workbook's Suffix, when Suffix is actually filled in).
    current_billet_number: the live Billet Number (per Order) from
        press_data -- how many billets have been run so far in this run.
    current_scheduled_billets: the live "Scheduled Billets" field from
        press_data. Unlike Job Number, this (along with Profile/Die
        Copy/Billet Number) is trustworthy -- but it can legitimately
        exceed the current job's own Excel-scheduled amount when the
        operator has informally consolidated one or more upcoming jobs
        into this same continuous run without updating the spreadsheet.
        When that happens, this attributes those jobs' Excel-scheduled
        billets to the current run instead of counting them as separate
        upcoming jobs, until the Excel total catches up to what the PLC
        says is actually being run.

    Walks the schedule forward from the current job, summing scheduled
    billets for this job (minus what's already run) plus every subsequent
    non-consolidated job, stopping only at the next explicit "ALLOY CHANGE"
    marker row. Adjacent jobs can legitimately differ in alloy *text*
    without a real alloy change (e.g. 6063T5 -> 6063T4 is a temper
    difference within the same base alloy, confirmed against a real
    schedule with no marker between them) -- the marker rows are the
    operators' own judgment call on what counts as a boundary, and that's
    more trustworthy than a string comparison across two systems
    (press_data's alloy codes vs. the schedule's alloy/temper text) with
    no reliable mapping between them. Crosses into the next shift's file
    if the current one runs out first -- jobs that haven't started are
    routinely re-listed across multiple shift files, so each Job # is
    only ever counted once across the whole walk (confirmed live: the
    current job itself was re-listed, blank, on the next shift's sheet).
    """

    # Shift boundaries and the workbook DATE cells are plant local time, not
    # UTC -- unlike the rest of this codebase's bookkeeping timestamps, this
    # has to match the operators' own wall clock or it'll pick the wrong file
    # right around a shift boundary.
    now = now or datetime.now()
    shift_date, shift_name = get_shift_info(now)

    entries = parse_schedule(find_shift_file(shift_date, shift_name))

    current_profile = _to_int(current_profile)
    current_die_copy = _to_int(current_die_copy)

    current_index = _find_current_index(entries, current_profile, current_die_copy, now)

    if current_index is None:
        return None  # can't confidently identify the current job -- can't predict

    current_alloy = entries[current_index]["alloy"]

    # Trust the PLC's own total for the current run over the (possibly
    # stale, pre-consolidation) Excel figure for just this one job line.
    remaining_billets = max(current_scheduled_billets - current_billet_number, 0)
    jobs_remaining = 0

    # Jobs that haven't started yet get re-listed across multiple shift
    # files (confirmed live: a job still in progress on 1st shift was also
    # listed, blank, on 2nd shift's file, presumably so the next shift's
    # operator can see it's still queued). Each Job # is only ever counted
    # once across the whole walk, however many times it's re-listed.
    seen_jobs = {entries[current_index]["job"]}

    index = current_index + 1

    # Any immediately-following job(s) whose Excel-scheduled billets are
    # already covered by the PLC's larger total have been informally
    # consolidated into this same run -- skip them here so the walk below
    # doesn't double-count them as separate upcoming jobs.
    consolidated_total = entries[current_index]["scheduledBillets"]
    while (
        index < len(entries)
        and "job" in entries[index]
        and consolidated_total < current_scheduled_billets
    ):
        entry = entries[index]
        if entry["job"] not in seen_jobs:
            seen_jobs.add(entry["job"])
            consolidated_total += entry["scheduledBillets"]
        index += 1

    hops = 0

    while hops < 3:  # safety cap: don't chase across more than a few shifts
        while index < len(entries):
            entry = entries[index]

            if "alloyChange" in entry:
                return {
                    "billetsRemaining": remaining_billets,
                    "jobsRemaining": jobs_remaining,
                    "alloy": current_alloy,
                }

            if entry["job"] not in seen_jobs:
                seen_jobs.add(entry["job"])
                remaining_billets += entry["scheduledBillets"]
                jobs_remaining += 1

            index += 1

        # ran off the end of this shift's file without hitting a boundary --
        # the alloy run continues into the next shift, per instruction to look
        # ahead at/just before shift change rather than wait for it
        shift_date, shift_name = get_next_shift_info(shift_date, shift_name)

        try:
            entries = parse_schedule(find_shift_file(shift_date, shift_name))
        except FileNotFoundError:
            break

        index = 0
        hops += 1

    return {
        "billetsRemaining": remaining_billets,
        "jobsRemaining": jobs_remaining,
        "alloy": current_alloy,
    }
