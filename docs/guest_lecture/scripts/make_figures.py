"""Draw every lecture figure with matplotlib from the tables in data/.

Run from docs/guest_lecture after scripts/make_lecture_data.py:
    python scripts/make_figures.py
Writes PDF figures to figures/.
"""

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIG = ROOT / "figures"

# Light-blue palette matching the Beamer theme color (#5B9BD5).
GOLD = "#BDD7EE"   # light fill
AGED = "#1F4E79"   # dark blue lines and edges
STEEL = "#595959"
BLUE = "#C0392B"   # highlight lines (minimum hosting capacity, no battery)
RED = "#C0392B"
BLACK = "#000000"

# Sized for a half-width Beamer column (16:9, ~2.8 in) so fonts match the slide.
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "mathtext.fontset": "dejavusans",
    "font.size": 8,
    "axes.labelsize": 8,
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


def numbers() -> dict[str, float]:
    text = (DATA / "numbers.tex").read_text(encoding="utf-8")
    values = {}
    for key, raw in re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", text):
        try:
            values[key] = float(raw.replace(",", ""))
        except ValueError:
            pass
    return values


def save(fig, name: str) -> None:
    fig.savefig(FIG / f"{name}.pdf")
    plt.close(fig)


def histogram() -> None:
    table = pd.read_csv(DATA / "hc_histogram.csv")
    fig, ax = plt.subplots(figsize=(2.9, 2.2))
    ax.bar(table.bin_mw, table["count"], width=90, color=GOLD, edgecolor=AGED, linewidth=0.5)
    ax.set_xlabel(r"$\min_t\ \mathrm{HC}_{k,t}$ over the peak day (MW)")
    ax.set_ylabel("buses")
    ax.set_xlim(0, 2000)
    save(fig, "hc_histogram")


def series(n: dict[str, float]) -> None:
    table = pd.read_csv(DATA / "hc_series.csv")
    buses = [(int(n["SerTwoBus"]), "load-driven", n["SerTwoMin"]), (int(n["SerOneBus"]), "structural", n["SerOneMin"])]
    fig, axes = plt.subplots(2, 1, figsize=(2.9, 2.5), sharex=True)
    for ax, (bus, label, minimum) in zip(axes, buses):
        ax.plot(table.hour, table[f"b{bus}"], color=AGED, linewidth=0.3)
        ax.axhline(minimum, color=BLUE, linestyle="--", linewidth=0.9)
        ax.set_title(f"bus {bus} ({label})", fontsize=7.5, pad=2)
        ax.set_ylabel("MW")
    axes[1].set_xlabel("hour of 2028 Jul–Dec")
    axes[1].set_xlim(0, 4416)
    fig.tight_layout(h_pad=0.6)
    save(fig, "hc_series")


def region(n: dict[str, float]) -> None:
    table = pd.read_csv(DATA / "pair_boundary.csv")
    hc_a, hc_b = n["PairHCa"], n["PairHCb"]
    fig, ax = plt.subplots(figsize=(2.8, 2.4))
    ax.fill_between(table.la, 0, table.lb, color=GOLD, alpha=0.6, linewidth=0)
    ax.plot(table.la, table.lb, color=AGED)
    ax.plot([hc_a, hc_a, 0], [0, hc_b, hc_b], color=STEEL, linestyle="--", linewidth=0.8)
    ax.text(hc_a * 0.97, hc_b * 0.95, "box of\nsingle-bus HCs", ha="right", va="top", fontsize=7)
    ax.text(hc_a * 0.32, hc_b * 0.3, r"$\mathcal{H}$", fontsize=11, color=AGED)
    ax.set_xlim(0, hc_a * 1.08)
    ax.set_ylim(0, hc_b * 1.12)
    ax.set_xlabel("new load at bus 1002 (MW)")
    ax.set_ylabel("new load at bus 1010 (MW)")
    save(fig, "hc_region")


def storage_day(n: dict[str, float]) -> None:
    table = pd.read_csv(DATA / "storage_day.csv")
    fig, ax = plt.subplots(figsize=(3.1, 2.1))
    ax.step(table.t, table.hc, where="post", color=AGED, label=r"$\mathrm{HC}_{k,t}$")
    ax.axhline(n["StoMean"], color=STEEL, linestyle=":", linewidth=1.2, label="average headroom")
    ax.axhline(n["StoWith"], color=BLACK, linestyle="--", linewidth=1.1, label="with battery")
    ax.axhline(n["StoMin"], color=BLUE, linewidth=1.3, label="no battery")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 6))
    ax.set_xlabel("hour of the peak day")
    ax.set_ylabel("MW")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, handlelength=1.8, columnspacing=1.0)
    save(fig, "storage_day")


def order_statistic() -> None:
    table = pd.read_csv(DATA / "order_statistic.csv")
    fig, ax = plt.subplots(figsize=(2.9, 2.2))
    ax.plot(table.K, table.hc, color=AGED)
    ax.set_xlim(0, table.K.max())
    ax.set_xlabel(r"$K$ = hours per half-year that may be curtailed")
    ax.set_ylabel(r"$\mathrm{HC}^{(K)}_k$ (MW)")
    save(fig, "order_statistic")


def site() -> None:
    """One student site (load, private generator, battery) at a network bus."""
    fig, ax = plt.subplots(figsize=(6.2, 2.2))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 4.4)
    ax.axis("off")

    def box(x, y, w, h, text, face, edge, size=8):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    facecolor=face, edgecolor=edge, linewidth=1))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size)

    def arrow(start, end, style="-|>"):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=9, linewidth=1.1, color=BLACK))

    box(0.1, 0.5, 2.4, 3.4, "ACTIVSg2000\nnetwork\n\nDCOPF with\nall teams' sites", "#DDEBF7", "#2F5D8A")
    ax.add_patch(plt.Circle((5.0, 2.2), 0.42, facecolor="white", edgecolor="#2F5D8A", linewidth=1.3))
    ax.text(5.0, 2.2, "bus $k$", ha="center", va="center", fontsize=8)
    arrow((2.5, 2.2), (4.58, 2.2), style="-")
    ax.text(3.6, 2.4, "grid purchase", ha="center", fontsize=7)
    ax.text(3.6, 1.82, r"paid at LMP $\lambda_{k,t}$", ha="center", fontsize=7)

    x_box, w_box = 8.1, 4.1
    parts = [
        (3.05, "IT load $\\alpha C$\nearns \\$6,500 per MWh served", "#FCE9D9", "#B26B00"),
        (1.75, "Private generator $0 \\leq g_t \\leq G$\n\\$80 / 150 / 250 per MWh", "#E2F0D9", "#3B7D23"),
        (0.45, "Battery $-P \\leq u_t \\leq P$\n$B = 4P$, no operating cost", "#EDE3F5", "#6A3D9A"),
    ]
    ax.add_patch(FancyBboxPatch((x_box - 0.25, 0.25), w_box + 0.5, 4.0, boxstyle="round,pad=0.02,rounding_size=0.15",
                                facecolor="none", edgecolor="#B26B00", linestyle="--", linewidth=1))
    ax.text(x_box + w_box / 2, 4.3, "your site = one row of the student CSV", ha="center", va="bottom",
            fontsize=7.5, color="#B26B00", fontweight="bold")
    tap = 7.4
    arrow((5.42, 2.2), (tap, 2.2), style="-")
    ax.plot([tap, tap], [0.95, 3.55], color=BLACK, linewidth=1.1)
    for y, text, face, edge in parts:
        box(x_box, y, w_box, 1.0, text, face, edge, size=7.5)
    arrow((tap, 3.55), (x_box, 3.55))
    arrow((x_box, 2.25), (tap, 2.25))
    arrow((tap, 0.95), (x_box, 0.95), style="<|-|>")
    save(fig, "site")


def main() -> None:
    n = numbers()
    histogram()
    series(n)
    region(n)
    storage_day(n)
    order_statistic()
    site()
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
