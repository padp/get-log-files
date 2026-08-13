"""
Log-counting pipeline for the "Log Pusher" camera. Feeds the physical
load-event side of confirming that when N logs get delivered to the table,
the same N logs get scanned into the PAD-Extrusion SHARED Plex location.

Calibration is hardcoded because the camera is fixed-mounted and does not
move. The four corners below were extracted (via HSV color-threshold +
contour detection) from a hand-drawn bounding box the user marked around the
log-table region on sample photo 6.jpg, at native 3840x2160 resolution.

Usage: python log_count.py <path-to-jpg> [<path-to-jpg> ...]
"""
import sys
import cv2
import numpy as np
from scipy.signal import find_peaks

# Hand-marked box corners on 6.jpg, native 3840x2160 -- TL, TR, BR, BL
_SRC = np.array([
    (1257, 428),   # top-left
    (1757, 418),   # top-right
    (1353, 1075),  # bottom-right
    (582, 1028),   # bottom-left
], dtype=np.float32)

_WARP_WIDTH, _WARP_HEIGHT = 772, 903

# The hand-drawn box's corners weren't quite a perfect parallelogram aligned
# to the true log axis, so mapping straight to an axis-aligned rectangle left
# a small residual tilt in the warped output (ridges weren't quite vertical).
# Measured directly by cross-correlating the ridge pattern between a row-band
# near the top and one near the bottom of the warp and finding what rotation
# zeroes out the horizontal shift between them -- came out to +2 degrees
# consistently across multiple frames. Baked into the destination rectangle
# (rather than a second warpAffine pass afterward) by rotating its corners
# about its own center, so the whole correction stays one warp operation.
_TILT_CORRECTION_DEG = 2.0

_dst_center = (_WARP_WIDTH / 2, _WARP_HEIGHT / 2)
_rot = cv2.getRotationMatrix2D(_dst_center, _TILT_CORRECTION_DEG, 1.0)
_axis_aligned_dst = np.array([
    [0, 0],
    [_WARP_WIDTH - 1, 0],
    [_WARP_WIDTH - 1, _WARP_HEIGHT - 1],
    [0, _WARP_HEIGHT - 1],
], dtype=np.float32)
_DST = cv2.transform(_axis_aligned_dst.reshape(-1, 1, 2), _rot).reshape(-1, 2)

_WARP_MATRIX = cv2.getPerspectiveTransform(_SRC, _DST)

# Two sampling bands within the warped crop, both run on every frame; when
# they disagree on the count, _gap_consistency picks whichever one's final
# peaks are more evenly spaced at the known pitch (see count_logs).
#
# Band 1 ("primary"): originally a fixed horizontal row range (rows
# 130-230) kept high to stay above the foreground safety fence -- but the
# fence crosses the frame diagonally (its top edge is much higher on the
# anchor/right side than on the left), so a horizontal band is really a
# compromise between staying clear of the fence on the right and staying
# clear of the brightest door glare (which turned out to sit right at the
# top of the hand-drawn box) on the left. The user hand-marked a band that
# instead runs parallel to the fence's actual diagonal, on a shortened
# `warp_log_region()` crop of 6.jpg (`6_warped_angledandshortened.jpg`,
# 2026-08-12) -- extracted via Hough line detection on the two drawn black
# boundary lines, both slope~0.966 (~44 deg). Validated against a 38-photo
# hand-labeled set: mean abs error 0.68 vs 1.47 for the old horizontal band
# (after also fixing _merge_close_peaks/_trim_to_pile below to anchor on the
# known fixed pitch instead of re-deriving it per frame -- the horizontal
# band produced corrupted anchor-side signal on some frames much more often
# than the angled one does).
#
# Band 2 ("rail-anchored"): the primary band's region sometimes still
# contains real background structure (a roof/wall panel and cross-brace
# truss, confirmed on a live frame 2026-08-13 -- the user first suspected
# the fence, and while that specific panel wasn't it, the same investigation
# led here) that echoes the log pitch closely enough to fool peak detection
# entirely -- all peaks landing on structure, missing the real pile. The
# user hand-marked the fence's top rail edge directly on that live frame
# (`logpusher_20260813_084801_review.jpg`) as a candidate new lower
# boundary; fit via linear regression on the marked pixels: slope=0.9473,
# intercept=211.5. Anchoring a band directly there eliminates that failure
# but introduces a different one (noisier/fragmented signal on some frames,
# `_MARGIN2` below pulls the band away from the rail to reduce that). Best
# single-band result found: 45px margin, mean abs error 0.68 / 24/38 (63%)
# exact on the labeled set (vs 18/38 for band 1 alone) -- but still fails
# badly on a few frames band 1 handles fine, hence running both.
_MARGIN = 25

_BAND1_SLOPE = 0.966
_BAND1_UPPER_INTERCEPT = -13.5
_BAND1_LOWER_INTERCEPT = 129.0

_RAIL_SLOPE = 0.9473
_RAIL_INTERCEPT = 211.5
_BAND2_HEIGHT = 142
_BAND2_MARGIN = 45
_BAND2_SLOPE = _RAIL_SLOPE
_BAND2_UPPER_INTERCEPT = _RAIL_INTERCEPT - _BAND2_HEIGHT - _BAND2_MARGIN
_BAND2_LOWER_INTERCEPT = _RAIL_INTERCEPT - _BAND2_MARGIN

# Average log-to-log pitch (px), from hand-marked ground truth on 6.jpg and
# 10.jpg (72.4px and 74.25px respectively). This press exclusively runs one
# billet diameter, so the pitch is a fixed constant, not something that
# needs per-job recalibration. Used for the measurement fallback and as a
# sanity check on the primary peak-counting method.
_PITCH = 73
_MAX_CAPACITY = round((_WARP_WIDTH - 2 * _MARGIN) / _PITCH)

# Local-energy (rolling std of the detrended profile) params for locating the
# pile/background boundary independently of the peak detector.
_ENERGY_WIN = 25
_ENERGY_RATIO = 0.3  # fraction of in-band peak energy that still counts as "real pile"


class CountResult:
    def __init__(self, count, method, confidence, detrended, peaks, boundary_x=None,
                 advisory=None, band="primary", bands_agreed=True):
        self.count = count
        self.method = method            # always "peak" -- see advisory below
        self.confidence = confidence    # 0-1
        self.detrended = detrended
        self.peaks = peaks
        self.boundary_x = boundary_x
        self.advisory = advisory        # dict or None -- see count_logs()
        self.band = band                # "primary" or "secondary" -- which band this result came from
        self.bands_agreed = bands_agreed

    def __repr__(self):
        flag = f", advisory={self.advisory['measured_estimate']}" if self.advisory else ""
        return f"CountResult(count={self.count}, confidence={self.confidence:.2f}, band={self.band!r}{flag})"


def warp_log_region(img):
    """Perspective-correct the fixed log-table region to a straightened crop."""
    return cv2.warpPerspective(img, _WARP_MATRIX, (_WARP_WIDTH, _WARP_HEIGHT))


def _detrended_profile(img, slope, upper_intercept, lower_intercept):
    warped = warp_log_region(img)
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(float)
    h, w = gray.shape

    xs = np.arange(_MARGIN, w - _MARGIN)
    profile = np.empty(len(xs), dtype=float)
    for i, x in enumerate(xs):
        y0 = max(0, int(round(slope * x + upper_intercept)))
        y1 = min(h, int(round(slope * x + lower_intercept)))
        profile[i] = gray[y0:y1, x].mean() if y1 > y0 else 0.0

    trend = cv2.GaussianBlur(profile.reshape(1, -1), (0, 0), sigmaX=25).flatten()
    return profile - trend


def _local_energy(detrended, win=_ENERGY_WIN):
    """Rolling std of the detrended profile -- how much local ridge/trough
    modulation is present at each x, regardless of whether any single bump
    is prominent enough to register as a find_peaks peak. Real log surface
    (even under weak, low-contrast lighting) modulates more than flat
    background (open doorway, roof beam)."""
    n = len(detrended)
    return np.array([detrended[max(0, i - win):i + win].std() for i in range(n)])


def _find_pile_boundary(energy):
    """Walk in from the anchored right edge and find the leftmost point that's
    still part of a contiguous high-energy (real pile) run, using a threshold
    relative to this frame's own peak energy -- so it works whether the frame
    is high-contrast or dim. Energy naturally dips at every log-to-log trough
    even within real pile, so brief below-threshold dips (shorter than a
    pitch) are bridged over first -- only a sustained drop counts as reaching
    the background."""
    threshold = _ENERGY_RATIO * energy.max()
    above = energy > threshold

    # bridge gaps shorter than ~half a pitch so normal inter-log troughs
    # don't get mistaken for the background boundary
    min_gap = int(_PITCH * 0.6)
    i = 0
    while i < len(above):
        if not above[i]:
            j = i
            while j < len(above) and not above[j]:
                j += 1
            if j - i < min_gap and i > 0 and j < len(above):
                above[i:j] = True
            i = j
        else:
            i += 1

    i = len(above) - 1
    while i > 0 and above[i]:
        i -= 1
    return i + 1


def _gap_consistency(peaks):
    """Mean absolute deviation of a peak list's gaps from the known fixed
    pitch -- lower means the final peaks are more evenly, plausibly spaced
    (real log ridges), higher means noisier/more irregular (more likely
    contaminated by background structure or a fragmented signal). Used to
    arbitrate between the two bands when they disagree on the count."""
    if len(peaks) < 2:
        return float("inf")
    gaps = np.diff(peaks)
    return float(np.mean(np.abs(gaps - _PITCH)))


def _analyze_band(img, slope, upper_intercept, lower_intercept):
    """Runs the full single-band pipeline (detrend, peak-detect, merge,
    trim, energy/boundary, advisory check) and returns a dict with
    everything count_logs needs to build a CountResult or compare against
    the other band."""
    detrended = _detrended_profile(img, slope, upper_intercept, lower_intercept)
    peaks, _ = find_peaks(detrended, prominence=3, distance=15)
    peaks = _merge_close_peaks(peaks)
    peaks = _trim_to_pile(peaks)

    energy = _local_energy(detrended)
    boundary_x = _find_pile_boundary(energy)
    leftmost_peak = peaks[0] if len(peaks) else len(detrended)

    capacity_ratio = len(peaks) / _MAX_CAPACITY
    confidence = min(1.0, 0.6 + 0.4 * capacity_ratio)

    # if the energy-based boundary sits well left of the leftmost claimed
    # peak, there's unclaimed signal the peak detector didn't count --
    # flagged for review, not acted on (see count_logs docstring)
    missed_span = leftmost_peak - boundary_x
    advisory = None
    if missed_span > 0.5 * _PITCH:
        span = (len(detrended) - 1) - boundary_x
        measured_estimate = max(1, round(span / _PITCH))
        advisory = {
            "reason": "possible missed log(s) left of leftmost detected peak",
            "measured_estimate": measured_estimate,
            "boundary_x": boundary_x,
        }
        confidence = min(confidence, 0.3)

    return {
        "count": len(peaks),
        "detrended": detrended,
        "peaks": peaks,
        "boundary_x": boundary_x,
        "advisory": advisory,
        "confidence": confidence,
    }


def count_logs(img):
    """Return a CountResult for a raw camera frame, from one of two
    independent sampling bands within the same warped crop (2026-08-13).

    Band 1 ("primary") runs parallel to the safety fence and was the sole
    method through 2026-08-12 (0.68 mean abs error / 18/38 exact on the
    38-photo labeled set). It sometimes samples real background structure
    (a roof/wall panel, cross-brace truss) that coincidentally echoes the
    log pitch closely enough to fool peak detection entirely on some
    frames. Band 2 ("secondary") is anchored near the fence's top rail
    (see `_BAND2_*` above) -- it avoids that specific failure but has its
    own (different) noisy-frame failure mode.

    Both run every time. If they agree on the count, that's a real
    cross-check and confidence uses the normal capacity-based formula. If
    they disagree, `_gap_consistency` picks whichever band's final peaks are
    more evenly spaced at the known pitch, and confidence is capped at 0.75
    -- disagreement between two independent methods is inherently less
    certain, even once one is chosen, and 0.75 sits below the 0.85 bar
    table_state.py requires for camera-consensus re-anchoring, so a
    disagreeing frame can't drive that on its own.

    There's also a pixel-measurement cross-check within each band (locate
    the pile/background boundary via local signal energy, divide the
    occupied span by the known average log pitch) that was originally wired
    up as an *overriding* fallback for when peak-detection looked like it
    missed something. That got demoted to advisory-only (2026-08-12) after
    a live frame showed the energy-boundary check can't reliably tell a
    real missed log apart from background structure that happens to echo
    the same ~73px pitch -- it silently turned a correct count of 6 into a
    wrong 7. The logic is kept here, surfaced as `result.advisory` rather
    than acting on it, in case a more robust distinguishing signal makes it
    trustworthy enough to reinstate."""
    band1 = _analyze_band(img, _BAND1_SLOPE, _BAND1_UPPER_INTERCEPT, _BAND1_LOWER_INTERCEPT)
    band2 = _analyze_band(img, _BAND2_SLOPE, _BAND2_UPPER_INTERCEPT, _BAND2_LOWER_INTERCEPT)

    if band1["count"] == band2["count"]:
        winner, name, agreed = band1, "primary", True
    else:
        c1 = _gap_consistency(band1["peaks"])
        c2 = _gap_consistency(band2["peaks"])
        if c2 < c1:
            winner, name, agreed = band2, "secondary", False
        else:
            winner, name, agreed = band1, "primary", False

    confidence = winner["confidence"] if agreed else min(winner["confidence"], 0.75)

    return CountResult(
        winner["count"], "peak", confidence, winner["detrended"], winner["peaks"],
        winner["boundary_x"], winner["advisory"], band=name, bands_agreed=agreed,
    )


def annotate(img, result):
    """Warped crop with the detected peak positions (and, if present, the
    advisory boundary) drawn on it -- a visual pair to the raw snapshot so
    what the algorithm is "seeing" can be audited frame-by-frame rather than
    inferred from a count and a confidence number alone."""
    warped = warp_log_region(img)
    vis = warped.copy()

    for p in result.peaks:
        x = int(p) + _MARGIN
        cv2.line(vis, (x, 0), (x, vis.shape[0]), (0, 0, 255), 2)

    if result.advisory:
        x = int(result.advisory["boundary_x"]) + _MARGIN
        cv2.line(vis, (x, 0), (x, vis.shape[0]), (0, 165, 255), 2)

    agree_flag = "" if result.bands_agreed else "  (bands disagreed)"
    label = f"count={result.count}  confidence={result.confidence:.2f}  band={result.band}{agree_flag}"
    cv2.putText(vis, label, (10, vis.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if result.advisory:
        adv_label = f"ADVISORY: alt estimate={result.advisory['measured_estimate']}"
        cv2.putText(vis, adv_label, (10, vis.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2, cv2.LINE_AA)

    return vis


def _merge_close_peaks(peaks, ratio=0.6):
    """Collapse spurious double-peaks (e.g. the twin highlight rims a single
    large-diameter log's curved surface can produce under backlighting) into
    one. Real log-to-log spacing is fairly uniform, so any gap much smaller
    than the known fixed pitch is almost certainly a split log rather than a
    genuinely separate one.

    Threshold used to be relative to this frame's own median gap rather than
    the known-constant pitch -- that self-referential estimate could get
    dragged down by the very double-peaks it was supposed to catch (a run of
    several small split-log gaps pulls the median down enough that those
    same gaps stop looking anomalous), letting the split survive uncaught.
    Anchoring to the fixed `_PITCH` avoids that."""
    peaks = np.asarray(peaks)
    threshold = ratio * _PITCH
    while len(peaks) >= 3:
        merged = [peaks[0]]
        changed = False
        for p in peaks[1:]:
            if p - merged[-1] < threshold:
                merged[-1] = (merged[-1] + p) // 2
                changed = True
            else:
                merged.append(p)
        peaks = np.array(merged)
        if not changed:
            break
    return peaks


def _trim_to_pile(peaks, tolerance=0.35):
    """Logs are pushed against a stop on the near (right) side of the crop
    and stack toward the far (left) side, so a partially-filled rack leaves
    empty space -- and background clutter -- on the left, not gaps in the
    middle. Real log-to-log spacing is regular; once we walk leftward from
    the anchored right edge and hit a gap that breaks from the known fixed
    pitch, everything further left is background, not logs, so drop it.

    Pitch used to be estimated from the two gaps nearest the anchor and then
    left to drift as the walk continued -- fragile, because if a double-peak
    survived right at the anchor (see _merge_close_peaks), that bad estimate
    became the reference for the whole walk and rejected real peaks further
    out (observed: a frame with 13 real candidate peaks got trimmed down to
    3). The pitch is a known physical constant here (fixed billet diameter),
    so there's no reason to re-derive or drift it per frame."""
    peaks = np.asarray(peaks)
    if len(peaks) < 3:
        return peaks
    gaps = np.diff(peaks)  # gaps[i] is the gap left of peaks[i+1]

    keep_from = len(peaks) - 1  # rightmost peak always kept
    for i in range(len(gaps) - 1, -1, -1):
        if abs(gaps[i] - _PITCH) <= tolerance * _PITCH:
            keep_from = i
        else:
            break
    return peaks[keep_from:]


if __name__ == "__main__":
    for path in sys.argv[1:]:
        img = cv2.imread(path)
        if img is None:
            print(f"{path}: could not read")
            continue
        result = count_logs(img)
        agree_flag = "" if result.bands_agreed else " DISAGREE"
        line = f"{path}: {result.count}  [confidence={result.confidence:.2f} band={result.band}{agree_flag}]"
        if result.advisory:
            line += f"  ADVISORY: {result.advisory['reason']} (alt estimate={result.advisory['measured_estimate']})"
        print(line)
