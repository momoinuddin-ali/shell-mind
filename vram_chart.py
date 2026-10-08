"""
vram_chart.py — renders the portfolio VRAM chart from vram_timeline.json.

The timeline is written by every agent run (workstation/model_zoo.py).
Usage:
    python vram_chart.py                 # full timeline
    python vram_chart.py --last 22       # zoom in on the last 22 samples
    python vram_chart.py --out chart.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parent

# Idle gaps longer than this separate two server sessions in the timeline —
# chart the most recent session instead of a mostly-empty diagonal.
SESSION_GAP_S = 60

_EVENT_LABELS = {
    "resident:router": "Router resident",
    "resident_unloaded:router": "Router parked",
    "copilot:unloaded": "Copilot unloaded",
    "copilot:gpu": "Copilot (GPU) on",
    "copilot:cpu": "Copilot (CPU) on",
}


def _event_label(event: str) -> str:
    if event in _EVENT_LABELS:
        return _EVENT_LABELS[event]
    kind, _, key = event.partition(":")
    verb = {"loaded": "Load", "unloaded": "Unload"}.get(kind, kind.title())
    return f"{verb} {key}" if key else event


def _trim_to_last_session(data: list[dict]) -> list[dict]:
    for i in range(1, len(data)):
        if data[i]["t"] - data[i - 1]["t"] > SESSION_GAP_S:
            return data[i:]
    return data


def _resolve_label_overlaps(fig, anns: list) -> None:
    """Nudge annotation labels until no two overlap and none clip the
    axes. Measures real rendered boxes, so placement adapts to any
    timeline instead of hoping a fixed offset cycle fits."""
    if not anns:
        return
    ax = anns[0].axes
    for _ in range(40):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [a.get_window_extent(renderer) for a in anns]
        ax_box = ax.get_window_extent(renderer)
        moved = False
        for j, ann in enumerate(anns):
            dx, dy = ann.xyann
            ndx, ndy = dx, dy
            bj = boxes[j]
            # keep inside the axes
            if bj.x0 < ax_box.x0 + 2:
                ndx += 14
            elif bj.x1 > ax_box.x1 - 2:
                ndx -= 14
            if bj.y1 > ax_box.y1 - 2:
                ndy -= 14
            elif bj.y0 < ax_box.y0 + 2:
                ndy += 14
            # step out of any overlap with an earlier label
            for i in range(j):
                if boxes[i].overlaps(bj):
                    j_cy = (bj.y0 + bj.y1) / 2
                    i_cy = (boxes[i].y0 + boxes[i].y1) / 2
                    ndy += 16 if j_cy <= i_cy else -16
                    break
            if (ndx, ndy) != (dx, dy):
                ann.xyann = (ndx, ndy)
                moved = True
        if not moved:
            return


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render the Shell-Mind VRAM timeline chart")
    ap.add_argument("--in", dest="infile", type=Path,
                    default=REPO_ROOT / "vram_timeline.json",
                    help="timeline JSON to read")
    ap.add_argument("--out", dest="outfile", type=Path,
                    default=REPO_ROOT / "portfolio_vram_chart.png",
                    help="chart PNG to write")
    ap.add_argument("--last", type=int, default=0, metavar="N",
                    help="plot only the last N samples (default: whole last session)")
    args = ap.parse_args()

    try:
        data = json.loads(args.infile.read_text())
    except FileNotFoundError:
        sys.exit(f"Error: {args.infile} not found. Run an agent prompt first!")
    if not data:
        sys.exit(f"Error: {args.infile} is empty.")

    data = _trim_to_last_session(data)
    if args.last > 0:
        data = data[-args.last:]

    t0 = data[0]["t"]
    times = [d["t"] - t0 for d in data]
    free = [d["free_gb"] for d in data]
    # Older timelines predate the total_gb probe; fall back to the RTX 5050.
    total = max(d.get("total_gb", 7.56) for d in data)

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(times, free, marker="o", color="#3FB950", linewidth=2.5,
            markersize=6, label="Free VRAM (GB)")
    ax.axhline(y=0, color="#B84A4A", linestyle="--", linewidth=2,
               label="OOM crash line (0 GB)")
    ax.axhline(y=total, color="#8B93A1", linestyle=":", linewidth=1.5,
               label=f"Max GPU VRAM ({total:.2f} GB)")

    # Stagger initial offsets, then let the collision resolver measure and
    # separate the rendered labels (thin leader lines stay attached).
    OFFSETS = [(0, 16), (0, -26), (16, 22), (-16, -30), (28, 14), (-28, -20)]
    anns = []
    for i, event in enumerate(d["event"] for d in data):
        if not event or event == "init":
            continue
        dx, dy = OFFSETS[i % len(OFFSETS)]
        anns.append(ax.annotate(
            _event_label(event), (times[i], free[i]),
            textcoords="offset points", xytext=(dx, dy),
            ha="center", fontsize=9, color="#C99B3D",
            arrowprops=dict(arrowstyle="-", color="#8B93A1",
                            lw=0.7, shrinkA=0, shrinkB=3)))
    _resolve_label_overlaps(fig, anns)

    ax.set_title("Shell-Mind: Zero-Sum VRAM Orchestration",
                 fontsize=16, color="#E8E6DE", pad=20)
    ax.set_xlabel("Execution time (seconds)", fontsize=12, color="#8B93A1")
    ax.set_ylabel("Available free VRAM (GB)", fontsize=12, color="#8B93A1")
    ax.set_ylim(-0.5, max(8.5, total + 0.8))
    ax.grid(True, color="#2B3340", linestyle="-", alpha=0.5)
    ax.legend(loc="lower left", frameon=True, facecolor="#161B22",
              edgecolor="#2B3340")

    fig.tight_layout()
    args.outfile.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.outfile, dpi=300)
    print(f"✅ Success! Chart saved as '{args.outfile}'")


if __name__ == "__main__":
    main()
