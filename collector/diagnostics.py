"""
Saves the 4-panel diagnostic chart (warped crop + detrended brightness +
local energy + HSV saturation + gradient magnitude, all with the same
pile/filled/bundle peaks marked) for a counted frame -- the same visual
format used throughout log_count.py's development to audit what the
algorithm is actually seeing, now generated automatically for whichever
frames table_state.py decides are worth keeping.

Deliberately a separate module from log_count.py: this pulls in matplotlib,
which the core counting path has no other reason to depend on. Kept local-
only on purpose (never uploaded to Mongo, unlike the plain annotated image
table_state.py mirrors for the dashboard's supervisory panel) -- this is
for whoever's actually digging through collector/camera_snapshots_annotated/
on the collector PC, not for remote viewing.
"""
import os
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from log_count import warp_log_region

_PANEL_SPECS = [
    ("brightness_detrended", "detrended\nbrightness", "steelblue"),
    ("energy", "local energy\n(rolling std)", "darkorange"),
    ("saturation_detrended", "HSV saturation\n(detrended)", "green"),
    ("gradient", "gradient magnitude\n(mean)", "purple"),
]


def diagnostic_chart_path(annotated_path):
    """Single source of truth for the companion-file naming convention, so
    camera.py (creates it) and table_state.py (deletes/renames it in lockstep
    with the plain annotated image) always agree on where it lives -- e.g.
    logpusher_20260817_140523.jpg -> logpusher_20260817_140523_diagnostic.png,
    and if the annotated image later gets renamed on keep (e.g. to
    ..._consensus__count6__conf0.92.jpg), calling this again on that new
    name gives the matching new diagnostic name."""
    directory, fname = os.path.split(annotated_path)
    stem, _ext = os.path.splitext(fname)
    return os.path.join(directory, f"{stem}_diagnostic.png")


def save_diagnostic_chart(img, result, out_path):
    """Writes the 4-panel diagnostic PNG to out_path. No-op (prints and
    returns) if result has no diagnostics attached, e.g. from a very old
    caller that hasn't been updated -- this should never actually happen
    from table_state.py, but a missing chart is not worth crashing a
    collector cycle over."""
    diag = result.diagnostics
    if diag is None:
        print(f"[DIAGNOSTICS] No diagnostics on result -- skipping chart for {out_path}")
        return

    xs = diag["xs"]
    pile_x = set(diag["pile"])
    filled_x = set(diag["filled"])
    bundle_x = set(diag["bundle"])

    warped = warp_log_region(img)
    warped_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)

    fig, axes = plt.subplots(5, 1, figsize=(14, 15), gridspec_kw={"height_ratios": [3, 1, 1, 1, 1]})

    ax_img = axes[0]
    ax_img.imshow(warped_rgb)
    for x in pile_x:
        color = "orange" if x in filled_x else "lime"
        ax_img.axvline(x, color=color, linewidth=2)
    for x in bundle_x:
        ax_img.axvline(x, color="red", linewidth=2)

    bundle_note = f"  +possible bundle (unconfirmed, {len(bundle_x)} peak(s))" if bundle_x else ""
    agree_note = "" if result.bands_agreed else "  (fallback/confluence used)"
    ax_img.set_title(
        f"count={result.count}  confidence={result.confidence:.2f}{agree_note}{bundle_note}\n"
        f"green=pile  orange=gap-filled  red=advisory bundle candidate (not counted)"
    )
    ax_img.set_xlim(0, warped.shape[1])

    for ax, (key, label, color) in zip(axes[1:], _PANEL_SPECS):
        signal = diag[key]
        ax.plot(xs, signal, color=color, linewidth=1)
        for x in pile_x:
            c = "orange" if x in filled_x else "lime"
            ax.axvline(x, color=c, linewidth=1, alpha=0.7)
        for x in bundle_x:
            ax.axvline(x, color="red", linewidth=1, alpha=0.7)
        ax.set_xlim(0, warped.shape[1])
        ax.set_ylabel(label, fontsize=9)
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("column (px, warped crop)")

    plt.tight_layout()
    try:
        fig.savefig(out_path, dpi=110)
    finally:
        plt.close(fig)
