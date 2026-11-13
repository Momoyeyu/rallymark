#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib==3.11.2"]
# ///
"""Plot macro parameter sensitivity from a completed evaluation CSV."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.evaluation / "summary.json").read_text())
    with (args.evaluation / "grid.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    ks = sorted({int(r["top_k"]) for r in rows})
    gaps = sorted({float(r["nearby_seconds"]) for r in rows})
    panels = [
        ("selection_f2", "Combined F2 (macro)", "viridis", 0, 1),
        ("event_05_f1", "Rally F1 / IoU >= 0.5 (macro)", "viridis", 0, 1),
        ("duration_recall", "Duration recall (macro)", "viridis", 0, 1),
        (
            "coverage_05_missed_rounds",
            "Rallies with <50% coverage (total)",
            "magma_r",
            0,
            None,
        ),
    ]
    matrices = {key: np.zeros((len(ks), len(gaps))) for key, *_ in panels}
    ki, gi = {v: i for i, v in enumerate(ks)}, {v: i for i, v in enumerate(gaps)}
    for row in rows:
        index = ki[int(row["top_k"])], gi[float(row["nearby_seconds"])]
        for key, matrix in matrices.items():
            matrix[index] += float(row[key])
    for key in matrices:
        if key != "coverage_05_missed_rounds":
            matrices[key] /= len(summary["videos"])
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout="constrained")
    selected = summary["recall_priority_alternative"]["parameters"]
    for ax, (key, title, cmap, vmin, vmax) in zip(axes.flat, panels, strict=True):
        picture = ax.imshow(
            matrices[key],
            origin="lower",
            aspect="auto",
            extent=[gaps[0] - 0.125, gaps[-1] + 0.125, ks[0] - 0.5, ks[-1] + 0.5],
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        ax.scatter(
            selected["nearby_seconds"],
            selected["top_k"],
            s=100,
            marker="x",
            color="red",
            linewidths=2,
        )
        ax.set(title=title, xlabel="Orphan neighborhood (s)", ylabel="TAD Top-N")
        fig.colorbar(picture, ax=ax, shrink=0.9)
    fig.suptitle(
        "Six matches: 6,327 configurations | red cross: recall-priority selection"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
