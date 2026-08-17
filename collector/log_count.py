"""
Log-counting pipeline for the "Log Pusher" camera. Feeds the physical
load-event side of confirming that when N logs get delivered to the table,
the same N logs get scanned into the PAD-Extrusion SHARED Plex location.

Calibration is hardcoded because the camera is fixed-mounted and does not
move. The four corners below were extracted (via HSV color-threshold +
contour detection) from a hand-drawn bounding box the user marked around the
log-table region on sample photo 6.jpg, at native 3840x2160 resolution.

Counting itself is gradient-edge-based (2026-08-15), replacing the earlier
brightness-ridge/dual-band approach -- validated against two fresh,
hand-counted 10-photo samples the algorithm was never tuned against
(8/10 and 8/10 exact, remaining misses diagnosed and fixed) plus the
original 38-photo labeled set. See collector/camera_snapshots_sample/ for
the labeled sets this was checked against.

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

# Sampling band within the warped crop: runs parallel to the safety fence
# (slope ~0.966, ~44 deg), hand-marked via Hough line detection on a
# shortened warp of 6.jpg. Column x within [_MARGIN, _WARP_WIDTH-_MARGIN)
# samples rows [slope*x+_BAND1_UPPER_INTERCEPT, slope*x+_BAND1_LOWER_INTERCEPT).
_MARGIN = 25
_BAND1_SLOPE = 0.966
_BAND1_UPPER_INTERCEPT = -13.5
_BAND1_LOWER_INTERCEPT = 129.0

# Average log-to-log pitch (px), from hand-marked ground truth. This press
# exclusively runs one billet diameter, so the pitch is a fixed constant,
# not something that needs per-job recalibration.
_PITCH = 73
_MAX_CAPACITY = round((_WARP_WIDTH - 2 * _MARGIN) / _PITCH)

# A physically bound, not-yet-loaded bundle always holds this many logs.
_BUNDLE_SIZE = 4

# Peak-shape params: a real log-to-log edge is a fast rise-then-fall in
# gradient magnitude (narrow width); background structure (roof beam, fence
# cross-brace) tends to be a slow, broad rise instead, even when its peak
# amplitude is comparable to a real edge. Width-capping rejects the broad
# ones outright; strict/loose prominence separate "definitely real" from
# "worth a second look during gap-filling."
_MAX_PEAK_WIDTH = 20
_STRICT_PROMINENCE = 25
_LOOSE_PROMINENCE = 10

# Gap-fit tolerances, in px, for deciding whether a gap between two
# confirmed peaks is "the pitch, maybe with missing logs in between" vs
# "not on the lattice at all -- probably a staged bundle boundary."
_TIGHT_FIT_TOL = 10   # this close to a clean multiple of the pitch: trust geometry alone
_GAP_FIT_TOL = 20      # this close: trust it only with amplitude/confluence corroboration
_ANCHOR_SLACK_TOL = 30  # extra slack for the link nearest the physical stop -- mechanical
                        # settling against it can make just that one gap atypical even
                        # when the rest of the chain fits the pitch perfectly
_MAX_FILL_K = 5

# A borderline (non-tight) single-pitch connection needs BOTH amplitude and
# cross-signal support to be trusted -- amplitude alone let a real staged-
# bundle edge and pure background structure through indistinguishably
# (confirmed on paired real/fake examples with identical local-energy
# readings), so a second signal is required, not just a lower bar.
_AMP_FRACTION = 0.3
_CONFLUENCE_TOL = 15
_BRIGHT_MIN_PROMINENCE = 12
_SAT_MIN_PROMINENCE = 8
_ENERGY_MIN_PROMINENCE = 4

# Local-energy (rolling std of detrended brightness) window.
_ENERGY_WIN = 25


class CountResult:
    def __init__(self, count, method, confidence, detrended, peaks, boundary_x=None,
                 advisory=None, band="gradient", bands_agreed=True):
        self.count = count
        self.method = method
        self.confidence = confidence    # 0-1
        self.detrended = detrended
        self.peaks = peaks              # absolute column positions (px) in the warped crop
        self.boundary_x = boundary_x
        self.advisory = advisory        # dict or None -- see count_logs()
        self.band = band                # descriptive only now (single-pipeline) -- kept for callers/logging
        self.bands_agreed = bands_agreed  # True for a clean gradient-only read; False if gap-fill/confluence was needed

    def __repr__(self):
        flag = f", advisory={self.advisory['measured_estimate']}" if self.advisory else ""
        return f"CountResult(count={self.count}, confidence={self.confidence:.2f}{flag})"


def warp_log_region(img):
    """Perspective-correct the fixed log-table region to a straightened crop."""
    return cv2.warpPerspective(img, _WARP_MATRIX, (_WARP_WIDTH, _WARP_HEIGHT))


def _band_stat(channel_2d, slope=_BAND1_SLOPE, upper=_BAND1_UPPER_INTERCEPT, lower=_BAND1_LOWER_INTERCEPT):
    """Mean value of channel_2d within the sampling band, per column."""
    h, w = channel_2d.shape
    xs = np.arange(_MARGIN, w - _MARGIN)
    out = np.empty(len(xs))
    for i, x in enumerate(xs):
        y0 = max(0, int(round(slope * x + upper)))
        y1 = min(h, int(round(slope * x + lower)))
        col = channel_2d[y0:y1, x]
        out[i] = col.mean() if len(col) else 0.0
    return xs, out


def _detrend(profile):
    trend = cv2.GaussianBlur(profile.reshape(1, -1), (0, 0), sigmaX=25).flatten()
    return profile - trend


def _local_energy(detrended, win=_ENERGY_WIN):
    """Rolling std of the detrended brightness profile -- how much local
    ridge/trough modulation is present at each x, regardless of whether any
    single bump is prominent enough to register as a find_peaks peak."""
    n = len(detrended)
    return np.array([detrended[max(0, i - win):i + win].std() for i in range(n)])


def _signal_profiles(img):
    """Computes all four signals used for counting, aligned on the same xs."""
    warped = warp_log_region(img)
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(float)
    sat = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)[:, :, 1].astype(float)

    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    grad_mag = np.sqrt(sobelx ** 2 + sobely ** 2)

    xs, gradient = _band_stat(grad_mag)
    _, brightness = _band_stat(gray)
    _, sat_mean = _band_stat(sat)

    detrended = _detrend(brightness)
    sat_detrended = _detrend(sat_mean)
    energy = _local_energy(detrended)

    return warped, xs, gradient, detrended, sat_detrended, energy


def _sharp_peaks(profile, min_prominence):
    """Peaks that rise and fall fast (narrow width) -- rejects the slow,
    broad bumps background structure produces even at comparable amplitude."""
    idx, props = find_peaks(profile, prominence=min_prominence, width=(None, _MAX_PEAK_WIDTH))
    return idx, props["prominences"]


def _first_per_pitch_window(peaks, proms, window_ratio=0.6):
    """Collapses spurious double-peaks (e.g. rim highlights on one wide log)
    within less than a pitch of each other, keeping the strongest of the
    group rather than the first -- matters once amplitude is used for
    anything downstream, since a weak-but-earlier candidate must not
    suppress a much stronger nearby one."""
    if len(peaks) == 0:
        return peaks, proms
    window = window_ratio * _PITCH
    groups = [[0]]
    for i in range(1, len(peaks)):
        if peaks[i] - peaks[groups[-1][-1]] < window:
            groups[-1].append(i)
        else:
            groups.append([i])
    kept = [max(g, key=lambda i: proms[i]) for g in groups]
    return peaks[kept], proms[kept]


def _nearest_within(candidates_x, target, tol):
    hits = [x for x in candidates_x if abs(x - target) <= tol]
    return min(hits, key=lambda x: abs(x - target)) if hits else None


def count_logs(img):
    """Return a CountResult for a raw camera frame.

    Counts individual logs from sharp edges in Sobel gradient magnitude
    within the fence-parallel sampling band -- a real log-to-log edge is a
    fast rise-then-fall (narrow width); background structure (roof beam,
    fence cross-brace) tends toward a slower, broader rise even at
    comparable peak height, so width-capping `find_peaks` separates the two
    far more reliably than brightness/amplitude alone did.

    The walk that turns raw peaks into a count starts from the rightmost
    (anchored against the physical stop, always trusted) and works left:
    - A gap that's a clean multiple of the pitch gets any missing interior
      slots filled -- first from a second, lower-threshold gradient pass,
      falling back to a detrended-brightness peak at the same expected
      position when gradient shows nothing there at all (confirmed on real
      frames: gradient depends on harsh directional shadow that diffuse
      lighting doesn't always provide, even when the log is really there).
    - A borderline-fit gap (not a clean multiple, not clearly off-lattice
      either) is only trusted if the far peak also shows a matching feature
      in brightness, saturation, AND local energy -- amplitude alone proved
      exploitable: a confirmed-real staged-bundle edge and a confirmed-fake
      background edge produced identical local-energy readings in testing.
    - The single link nearest the anchor gets extra gap tolerance before the
      walk gives up, since mechanical settling against the stop can make
      just that one connection atypical even when the rest of the chain
      fits the pitch perfectly.
    - Whatever's left unclaimed past a broken link is a possible staged
      bundle (always exactly 4 logs when real, physically bound together
      until its banding is cut) -- surfaced as `result.advisory`, not
      auto-added to `count`, since real bundle edges and spurious
      background edges were found to be indistinguishable by energy,
      prominence, or gap-fit alone.
    """
    warped, xs, gradient, detrended, sat_detrended, energy = _signal_profiles(img)

    strict_idx, strict_prom = _sharp_peaks(gradient, _STRICT_PROMINENCE)
    confirmed_idx, confirmed_prom = _first_per_pitch_window(strict_idx, strict_prom)
    confirmed_x = xs[confirmed_idx]

    loose_idx, _ = _sharp_peaks(gradient, _LOOSE_PROMINENCE)
    loose_x = xs[loose_idx]

    bright_idx, _ = find_peaks(detrended, prominence=_BRIGHT_MIN_PROMINENCE, distance=15)
    bright_x = xs[bright_idx]
    sat_idx, _ = find_peaks(sat_detrended, prominence=_SAT_MIN_PROMINENCE, distance=15)
    sat_x = xs[sat_idx]
    energy_idx, _ = find_peaks(energy, prominence=_ENERGY_MIN_PROMINENCE, distance=15)
    energy_x = xs[energy_idx]

    def confluence_ok(x, min_hits=2):
        hits = sum(_nearest_within(sig, x, _CONFLUENCE_TOL) is not None
                   for sig in (bright_x, sat_x, energy_x))
        return hits >= min_hits

    if len(confirmed_x) == 0:
        return CountResult(0, "gradient_peak", 0.0, gradient, [], band="gradient", bands_agreed=False)

    order = np.argsort(confirmed_x)
    confirmed_x = confirmed_x[order]
    confirmed_prom = confirmed_prom[order]

    pile = [confirmed_x[-1]]
    pile_prom = [confirmed_prom[-1]]
    used_fallback = False
    i = len(confirmed_x) - 1
    is_first_link = True
    while i > 0:
        b, a = confirmed_x[i], confirmed_x[i - 1]
        a_prom = confirmed_prom[i - 1]
        gap = b - a
        k = max(1, round(gap / _PITCH))
        residual = abs(gap - k * _PITCH)
        reference = float(np.median(pile_prom))
        tight_fit = residual <= _TIGHT_FIT_TOL
        borderline_ok = a_prom >= _AMP_FRACTION * reference and confluence_ok(a)
        tol = _ANCHOR_SLACK_TOL if is_first_link else _GAP_FIT_TOL

        if residual <= tol and k <= _MAX_FILL_K and (tight_fit or borderline_ok or is_first_link):
            for m in range(1, k):
                expected = b - (k - m) * _PITCH  # anchored from the trusted (right) side
                cand = _nearest_within(loose_x, expected, _GAP_FIT_TOL)
                if cand is None:
                    cand = _nearest_within(bright_x, expected, _GAP_FIT_TOL)
                    if cand is not None:
                        used_fallback = True
                if cand is not None:
                    pile.insert(0, cand)
                    pile_prom.insert(0, reference)
            pile.insert(0, a)
            pile_prom.insert(0, a_prom)
            if not tight_fit:
                used_fallback = True
            i -= 1
            is_first_link = False
            continue
        break

    bundle_peaks = list(confirmed_x[:i])

    count = len(pile)
    capacity_ratio = count / _MAX_CAPACITY

    # Confidence reflects how much inference went into this specific read,
    # not how full the table happens to be -- a clean, width/prominence-
    # filtered gradient read of 3 logs is exactly as trustworthy as one of
    # 9, since the shape-based filtering is what validates it either way.
    # The old capacity-ratio-scaled formula didn't distinguish these and
    # structurally capped confidence below 0.85 for any count <= 6 (0.6 +
    # 0.4*(6/10) = 0.84) -- so a real, repeated, correct low-count reading
    # could never reach table_state.py's consensus threshold at all, and a
    # genuine load event onto a mostly-empty table got silently stuck
    # behind the furnace's decrement-only side (confirmed live 2026-08-17:
    # table physically had 5 logs, camera read 5 cleanly and repeatedly,
    # confirmedCount stayed wedged at 3).
    advisory = None
    if bundle_peaks:
        advisory = {
            "reason": "possible staged bundle before the counted pile (unconfirmed)",
            "measured_estimate": count + _BUNDLE_SIZE,
            "boundary_x": bundle_peaks[-1],
        }
        confidence = 0.3
    elif used_fallback:
        confidence = 0.75
    else:
        confidence = min(1.0, 0.90 + 0.10 * capacity_ratio)

    return CountResult(
        count, "gradient_peak", confidence, gradient, pile,
        boundary_x=pile[0] if pile else None, advisory=advisory,
        band="gradient", bands_agreed=not (bundle_peaks or used_fallback),
    )


def annotate(img, result):
    """Warped crop with the detected peak positions (and, if present, the
    advisory bundle boundary) drawn on it -- a visual pair to the raw
    snapshot so what the algorithm is "seeing" can be audited frame-by-frame
    rather than inferred from a count and a confidence number alone."""
    warped = warp_log_region(img)
    vis = warped.copy()

    for p in result.peaks:
        x = int(p)
        cv2.line(vis, (x, 0), (x, vis.shape[0]), (0, 0, 255), 2)

    if result.advisory:
        x = int(result.advisory["boundary_x"])
        cv2.line(vis, (x, 0), (x, vis.shape[0]), (0, 165, 255), 2)

    agree_flag = "" if result.bands_agreed else "  (fallback used)"
    label = f"count={result.count}  confidence={result.confidence:.2f}{agree_flag}"
    cv2.putText(vis, label, (10, vis.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    if result.advisory:
        adv_label = f"ADVISORY: alt estimate={result.advisory['measured_estimate']}"
        cv2.putText(vis, adv_label, (10, vis.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2, cv2.LINE_AA)

    return vis


if __name__ == "__main__":
    for path in sys.argv[1:]:
        img = cv2.imread(path)
        if img is None:
            print(f"{path}: could not read")
            continue
        result = count_logs(img)
        agree_flag = "" if result.bands_agreed else " (fallback used)"
        line = f"{path}: {result.count}  [confidence={result.confidence:.2f}{agree_flag}]"
        if result.advisory:
            line += f"  ADVISORY: {result.advisory['reason']} (alt estimate={result.advisory['measured_estimate']})"
        print(line)
