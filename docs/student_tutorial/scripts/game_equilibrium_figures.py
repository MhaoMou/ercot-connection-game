"""Figures for game_equilibrium_ieee14.py (reads the JSON/NPZ results).

Run through ``game_equilibrium_ieee14.py --figures-only`` or directly:
    python docs/student_tutorial/scripts/game_equilibrium_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm, LinearSegmentedColormap

LIGHT = "#BDD7EE"
DARK = "#1F4E79"
GREY = "#595959"
RED = "#C0392B"
LABEL_BOX = dict(facecolor="white", alpha=0.85, edgecolor="none", pad=0.6)
TEXT_WIDTH = 6.5

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "mathtext.fontset": "dejavusans",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.2,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
})


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def region_figure(out: Path, fig_dir: Path) -> None:
    data = _load(out / "exp1_fixed_buses.json")
    if not data:
        return
    cases = [name for name in ("a_13_14", "b_1_2") if name in data]
    fig, axes = plt.subplots(1, len(cases), figsize=(TEXT_WIDTH * 0.5 * len(cases), 3.4), squeeze=False)
    for ax, name in zip(axes[0], cases):
        case = data[name]
        sites = case["sites"]
        boundary = np.array([pt for pt in case["boundary"] if pt[1] is not None])
        xs = np.concatenate([[0.0], boundary[:, 0], [boundary[-1, 0]]])
        ys = np.concatenate([[0.0], boundary[:, 1], [0.0]])
        ax.fill(xs, ys, color=LIGHT, zorder=1, label="feasible region $H$")
        ax.plot(boundary[:, 0], boundary[:, 1], color=DARK, lw=1.0, zorder=2)
        top = max(boundary[:, 0].max(), boundary[:, 1].max()) * 1.08
        run0 = next((r for r in case["dynamics"] if r["mode"] == "sequential" and r["start_index"] == 1), None)
        if run0:
            top = max(top, max(max(p) for p in run0["path"]) * 1.05)
        ax.plot([0, top], [0, top], color=GREY, lw=0.5, ls=":", zorder=1)
        # planner optimum face: points of H with maximal total
        total = case["planner_total_mw_lp"]
        face = boundary[np.abs(boundary.sum(axis=1) - total) < 1e-3 * max(total, 1)]
        if len(face) >= 2:
            ax.plot(face[:, 0], face[:, 1], color=DARK, lw=3.0, alpha=0.55, solid_capstyle="butt",
                    zorder=3, label="planner optima (max total MW)")
        opt = case["planner_lp_mw"]
        ax.plot(*opt, marker="s", ms=4.5, color=DARK, zorder=5, ls="none",
                label=f"LP planner vertex ({opt[0]:.1f}, {opt[1]:.1f})")
        # best-response path from the first random start (sequential)
        run = next((r for r in case["dynamics"] if r["mode"] == "sequential" and r["start_index"] == 1), None)
        if run:
            path = np.array(run["path"])
            for (x0, y0), (x1, y1) in zip(path[:-1], path[1:]):
                if abs(x0 - x1) + abs(y0 - y1) > 1e-9:
                    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                                arrowprops=dict(arrowstyle="-|>", color=GREY, lw=0.7, mutation_scale=7), zorder=4)
            ax.plot(path[0, 0], path[0, 1], marker="o", ms=3.5, mfc="white", mec=GREY, ls="none", zorder=5,
                    label="BR path (sequential)")
        w = case["w_mw"]
        ax.plot(*w, marker="*", ms=9, color=RED, zorder=6, ls="none",
                label=f"$w$ = ({w[0]:.2f}, {w[1]:.2f})")
        ax.set_xlim(0, top)
        ax.set_ylim(0, top)
        ax.set_aspect("equal")
        ax.set_xlabel(f"request $r_1$ at bus {sites[0]} (MW)")
        ax.set_ylabel(f"request $r_2$ at bus {sites[1]} (MW)")
        ax.set_title(f"({'ab'[cases.index(name)]}) buses {sites[0]} and {sites[1]}", loc="left")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, handlelength=1.4)
    fig.tight_layout(w_pad=1.5)
    fig.savefig(fig_dir / "ne_region_2team.pdf")
    plt.close(fig)


def br_check_figure(out: Path, fig_dir: Path) -> None:
    """Deviation gain u_i(r_i, w_-i) - u_i(w) near w, with and without energy cost."""
    import csv

    data = _load(out / "exp1_fixed_buses.json")
    path = out / "exp1_deviation_scan.csv"
    if not data or not path.is_file():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    cases = [name for name in ("a_13_14", "b_1_2", "c_9_13_14") if name in data]
    fig, axes = plt.subplots(1, len(cases), figsize=(TEXT_WIDTH, 2.3), squeeze=False, sharey=True)
    colors = [DARK, RED, GREY]
    for ax, name in zip(axes[0], cases):
        case = data[name]
        no_energy = {c["team"]: c for c in case["modes"]["no_energy"]["best_response_check"]}
        for i, check in enumerate(case["best_response_check"]):
            pts = sorted((float(r["r_mw"]), float(r["score"]), float(r["score_no_energy"]))
                         for r in rows if r["case"] == name and r["team"] == check["team"])
            x = np.array([p[0] for p in pts]) - check["w_mw"]
            keep = (x >= -4.0) & (x <= 3.0)
            gain = (np.array([p[1] for p in pts]) - check["payoff_at_w"]) / 1e3
            gain0 = (np.array([p[2] for p in pts]) - no_energy[check["team"]]["payoff_at_w"]) / 1e3
            ax.plot(x[keep], gain[keep], lw=0.9, color=colors[i % 3], marker="o", ms=1.5,
                    label=f"bus {check['bus']}")
            ax.plot(x[keep], gain0[keep], lw=0.8, ls=":", color=colors[i % 3])
        ax.axhline(0, color=GREY, lw=0.4)
        ax.axvline(0, color=GREY, lw=0.4)
        ax.set_ylim(-700, 700)
        ax.set_xlim(-4, 3)
        ax.set_xlabel("own deviation $r_i - w_i$ (MW)")
        ax.set_title(f"({'abc'[cases.index(name)]}) buses {', '.join(case['sites'])}", loc="left")
        ax.legend(frameon=False, loc="upper right")
    axes[0][0].set_ylabel("gain over staying at $w_i$ (\\$k)")
    axes[0][-1].plot([], [], color=GREY, lw=0.8, ls=":", label="without energy cost")
    axes[0][-1].legend(frameon=False, loc="center left", bbox_to_anchor=(1.0, 0.5))
    fig.tight_layout(w_pad=0.8)
    fig.savefig(fig_dir / "ne_br_check.pdf")
    plt.close(fig)


def matrix_figure(out: Path, fig_dir: Path) -> None:
    path = out / "exp2_payoff_matrix.npz"
    summary = _load(out / "exp2_two_team.json")
    if not path.is_file() or not summary:
        return
    npz = np.load(path, allow_pickle=False)
    A, B, labels = npz["A"] / 1e6, npz["B"] / 1e6, [str(s) for s in npz["strategies"]]
    m = len(labels)
    buses = [lab.split(":")[0] if lab != "out" else "out" for lab in labels]
    fig, ax = plt.subplots(figsize=(TEXT_WIDTH * 0.62, TEXT_WIDTH * 0.58))
    clip = max(abs(A.max()), 1e-6)
    shown = np.clip(A, -2 * clip, clip)
    cmap = LinearSegmentedColormap.from_list("rb", [RED, "#F4D6D2", "white", LIGHT, DARK])
    image = ax.imshow(shown, cmap=cmap, norm=TwoSlopeNorm(vmin=-2 * clip, vcenter=0.0, vmax=clip),
                      origin="upper", interpolation="nearest")
    # column player's best response to each row (team-b BR to team-a) and team-a BR to each column
    br_a = A.argmax(axis=0)
    br_b = B.argmax(axis=1)
    ax.plot(np.arange(m), br_a, ls="none", marker="_", ms=3, color="black", mew=0.6, label="team A best response")
    ax.plot(br_b, np.arange(m), ls="none", marker="|", ms=3, color=GREY, mew=0.6, label="team B best response")
    lookup = {lab: k for k, lab in enumerate(labels)}
    for item in summary["pure_equilibria"]:
        i, j = lookup[item["team_a"]], lookup[item["team_b"]]
        ax.plot(j, i, marker="*", ms=9, mfc=RED, mec="black", mew=0.4, ls="none")
    ax.plot([], [], marker="*", ms=8, mfc=RED, mec="black", mew=0.4, ls="none", label="pure NE")
    edges = [k for k in range(1, m) if buses[k] != buses[k - 1]]
    for k in edges:
        ax.axhline(k - 0.5, color=GREY, lw=0.3)
        ax.axvline(k - 0.5, color=GREY, lw=0.3)
    starts = [0] + edges
    ends = edges + [m]
    centers = [(s + e - 1) / 2 for s, e in zip(starts, ends)]
    names = ["out" if buses[s] == "out" else f"bus {buses[s]}" for s in starts]
    ax.set_xticks(centers, names, rotation=90)
    ax.set_yticks(centers, names)
    ax.tick_params(length=0)
    ax.set_xlabel("team B site (MW increasing within each bus)")
    ax.set_ylabel("team A site (MW increasing within each bus)")
    cbar = fig.colorbar(image, ax=ax, shrink=0.75, pad=0.02)
    cbar.set_label("team A score (\\$M, clipped)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3, frameon=False, markerscale=1.5)
    fig.savefig(fig_dir / "ne_payoff_matrix.pdf")
    plt.close(fig)


def dynamics_figure(out: Path, fig_dir: Path) -> None:
    data = _load(out / "exp3_multi_team.json")
    exp1 = _load(out / "exp1_fixed_buses.json")
    panels = []
    if exp1 and "c_9_13_14" in exp1:
        panels.append("c")
    if data:
        panels += [k for k in ("n3", "n4") if k in data]
    if not panels:
        return
    fig, axes = plt.subplots(1, len(panels), figsize=(TEXT_WIDTH, 2.3), squeeze=False)
    for p_index, (ax, key) in enumerate(zip(axes[0], panels)):
        tag = "abc"[p_index]
        if key == "c":
            case = exp1["c_9_13_14"]
            colors = [DARK, RED, GREY]
            for mode, style in (("lmp", "-"), ("no_energy", ":")):
                run = next(r for r in case["modes"][mode]["dynamics"]
                           if r["mode"] == "sequential" and r["start_index"] == 1)
                path = np.array(run["path"])
                for i, bus in enumerate(case["sites"]):
                    ax.plot(range(len(path)), path[:, i], ls=style, color=colors[i], lw=0.9,
                            label=f"bus {bus}" if mode == "lmp" else None)
            for i, wi in enumerate(case["w_mw"]):
                ax.axhline(wi, color=colors[i], lw=0.4, alpha=0.6)
            ax.plot([], [], color=GREY, ls=":", label="without energy cost")
            ax.set_ylim(0, 75)
            ax.set_xlim(0, 45)
            ax.set_xlabel("best-response move")
            ax.set_ylabel("request (MW)")
            ax.set_title(f"({tag}) buses 9, 13, 14, fixed", loc="left")
            ax.legend(frameon=False, loc="lower right", ncol=2, fontsize=6)
            continue
        block = data[key]
        for run in block["runs"]:
            welfare = [p["welfare"] / 1e6 for p in run["path"]]
            ax.plot(range(len(welfare)), welfare, color=DARK if run["converged"] else RED,
                    lw=0.8, alpha=0.85, marker="o", ms=2)
            drops = [k for k, p in enumerate(run["path"]) if p["dropped"]]
            if drops:
                ax.plot(drops, [welfare[k] for k in drops], ls="none", marker="x", ms=4, color=RED)
        planner = block["planner_continuous"]["welfare"] / 1e6
        ax.axhline(planner, color=RED, lw=0.8, ls="--")
        ax.text(0.98, planner, "planner optimum", ha="right", va="bottom", color=RED,
                transform=ax.get_yaxis_transform(), fontsize=7)
        ax.set_xlabel("best-response move")
        ax.set_ylabel("total score (\\$M)")
        ax.set_title(f"({tag}) {key[1:]} teams, bus choice", loc="left")
        ymin = min(min(p["welfare"] for p in run["path"]) for run in block["runs"]) / 1e6
        ax.set_ylim(max(ymin, -0.5 * planner), planner * 1.12)
    fig.tight_layout(w_pad=1.0)
    fig.savefig(fig_dir / "ne_dynamics.pdf")
    plt.close(fig)


def make_all(out: Path, fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    region_figure(out, fig_dir)
    br_check_figure(out, fig_dir)
    matrix_figure(out, fig_dir)
    dynamics_figure(out, fig_dir)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    make_all(root / "data" / "game_equilibrium", root / "figures")
