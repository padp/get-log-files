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
import xlrd

SCHEDULE_DIR = "Y:/PADUCAH - Press Schedules/PRESS REPORTS"

WEEKDAY_LETTERS = "ABCDEFG"  # Monday=A .. Sunday=G, matches the file naming convention

# (ordinal name, filename suffix number) per shift, keyed by which shift a given hour falls in
SHIFT_1ST = "1st"
SHIFT_2ND = "2nd"
SHIFT_3RD = "3rd"

SHIFT_SUFFIX = {SHIFT_1ST: 2, SHIFT_2ND: 3, SHIFT_3RD: 1}
SHIFT_ORDER = [SHIFT_1ST, SHIFT_2ND, SHIFT_3RD]  # chronological order within a shift-date

COL_DIE = 0
COL_SUFFIX = 1
COL_JOB = 2
COL_PART = 3
COL_ALLOY = 4
COL_SCHEDULED_BILLETS = 5
COL_BILLET_LENGTH = 9
COL_BILLETS_RAN = 10


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


def shift_file_path(shift_date, shift_name):
    letter = WEEKDAY_LETTERS[shift_date.weekday()]
    suffix = SHIFT_SUFFIX[shift_name]
    weekday_name = shift_date.strftime("%A")

    filename = f"{letter}-{suffix} Press Report - {weekday_name} {shift_name} Shift.xls"
    return f"{SCHEDULE_DIR}/{filename}"


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
        })

    return entries


def predict_billets_until_alloy_change(current_job_number, current_billet_number, now=None):
    """
    current_job_number: the live Job Number (#) from press_data, for the job
        actually running right now.
    current_billet_number: the live Billet Number (per Order) from press_data
        -- how many billets have been run so far in that job.

    Walks the schedule forward from the current job, summing scheduled
    billets for this job (minus what's already run) plus every subsequent
    job, stopping only at the next explicit "ALLOY CHANGE" marker row.
    Adjacent jobs can legitimately differ in alloy *text* without a real
    alloy change (e.g. 6063T5 -> 6063T4 is a temper difference within the
    same base alloy, confirmed against a real schedule with no marker
    between them) -- the marker rows are the operators' own judgment call
    on what counts as a boundary, and that's more trustworthy than a
    string comparison across two systems (press_data's alloy codes vs.
    the schedule's alloy/temper text) with no reliable mapping between
    them. Crosses into the next shift's file if the current one runs out
    first.
    """

    # Shift boundaries and the workbook DATE cells are plant local time, not
    # UTC -- unlike the rest of this codebase's bookkeeping timestamps, this
    # has to match the operators' own wall clock or it'll pick the wrong file
    # right around a shift boundary.
    now = now or datetime.now()
    shift_date, shift_name = get_shift_info(now)

    entries = parse_schedule(shift_file_path(shift_date, shift_name))

    current_index = next(
        (i for i, e in enumerate(entries) if "job" in e and e["job"] == int(current_job_number)),
        None
    )

    if current_index is None:
        return None  # current job isn't in this shift's schedule -- can't predict

    current_alloy = entries[current_index]["alloy"]
    remaining_billets = max(entries[current_index]["scheduledBillets"] - current_billet_number, 0)
    jobs_remaining = 0

    index = current_index + 1
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

            remaining_billets += entry["scheduledBillets"]
            jobs_remaining += 1
            index += 1

        # ran off the end of this shift's file without hitting a boundary --
        # the alloy run continues into the next shift, per instruction to look
        # ahead at/just before shift change rather than wait for it
        shift_date, shift_name = get_next_shift_info(shift_date, shift_name)

        try:
            entries = parse_schedule(shift_file_path(shift_date, shift_name))
        except FileNotFoundError:
            break

        index = 0
        hops += 1

    return {
        "billetsRemaining": remaining_billets,
        "jobsRemaining": jobs_remaining,
        "alloy": current_alloy,
    }
