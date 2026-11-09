#!/usr/bin/env python3
"""Generate original concept figures (matplotlib, computed geometry).

Output goes to data/concepts/images/ (gitignored). Figures are original
work (no OpenStax asset copying) so they can ship commercially.
Re-run to regenerate any figure from its data, not by hand-editing the SVG.
"""
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

OUT = pathlib.Path("data/concepts/images")
OUT.mkdir(parents=True, exist_ok=True)


def save(fig, name):
    fig.savefig(OUT / name, format="svg", bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    print(name)


# 1. Trig: exact 3-4-5 right triangle.
fig, ax = plt.subplots(figsize=(5, 4))
A = np.array([0, 0])
B = np.array([4, 0])
C = np.array([4, 3])
ax.add_patch(plt.Polygon([A, B, C], closed=True, fill=False, edgecolor="#0f172a", linewidth=2))
ax.plot([0, 4], [0, 0], color="#0f172a", linewidth=2)
ax.plot([4, 4], [0, 3], color="#0f172a", linewidth=2)
ax.plot([0, 4], [0, 3], color="#2563eb", linewidth=2.5)
ax.add_patch(patches.Rectangle((3.6, 0), 0.4, 0.4, fill=False, edgecolor="#0f172a", linewidth=1.2))
ax.set_xlim(-0.5, 4.8)
ax.set_ylim(-0.5, 3.8)
ax.set_aspect("equal")
ax.axis("off")
ax.text(2, -0.3, "Adjacent (cos)", ha="center", fontsize=10)
ax.text(4.2, 1.5, "Opposite (sin)", va="center", rotation=90, fontsize=10)
ax.text(1.4, 0.9, "Hypotenuse", ha="center", fontsize=10, color="#2563eb")
ax.text(2, 1.6, "θ", fontsize=16, ha="center")
ax.set_title("Right Triangle: SOH CAH TOA")
save(fig, "fig_trig_right_triangle.svg")

# 2. Number bases: binary place value.
fig, ax = plt.subplots(figsize=(6, 2.5))
ax.axis("off")
for i, (h, v, dgt) in enumerate(zip(["2^0", "2^1", "2^2", "2^3", "2^4"], ["1", "2", "4", "8", "16"], ["1", "0", "1", "1", "0"])):
    ax.add_patch(patches.Rectangle((i, 0), 1, 1.5, fill=True, facecolor="#e8eef7" if i % 2 == 0 else "white", edgecolor="#0f172a", linewidth=1.2))
    ax.text(i + 0.5, 1.35, h, ha="center", va="center", fontsize=9)
    ax.text(i + 0.5, 0.9, v, ha="center", va="center", fontsize=11)
    ax.text(i + 0.5, 0.4, dgt, ha="center", va="center", fontsize=12, weight="bold")
ax.set_xlim(0, 5)
ax.set_ylim(0, 1.8)
ax.set_title("Binary place values: 10110_2 = 16+4+2 = 22")
save(fig, "fig_math_number_bases_place_value.svg")

# 3. Sets Venn.
fig, ax = plt.subplots(figsize=(5, 4))
ax.axis("off")
ax.add_patch(patches.Circle((0, 1), 1.2, fill=True, facecolor="#dbeafe", edgecolor="#1d4ed8", linewidth=2, alpha=0.9))
ax.add_patch(patches.Circle((1.5, 1), 1.2, fill=True, facecolor="#fef3c7", edgecolor="#b45309", linewidth=2, alpha=0.9))
ax.text(-0.6, 1.3, "A only", fontsize=11)
ax.text(2.1, 1.3, "B only", fontsize=11)
ax.text(0.75, 1, "A and B", ha="center", fontsize=11, weight="bold")
ax.text(0.75, -0.3, "Union = A and B together", ha="center", fontsize=10)
ax.set_xlim(-1.5, 3)
ax.set_ylim(-0.6, 2.5)
ax.set_aspect("equal")
ax.set_title("Sets: Union and Intersection")
save(fig, "fig_math_sets_venn.svg")

# 4. Polynomial graph.
fig, ax = plt.subplots(figsize=(6, 3.5))
x = np.linspace(-2, 2, 200)
ax.plot(x, 2 * x**2 - 3 * x + 1, color="#2563eb", linewidth=2)
ax.axhline(0, color="grey", linewidth=0.8)
ax.axvline(0, color="grey", linewidth=0.8)
ax.set_xlabel("x")
ax.set_ylabel("y")
ax.grid(True, alpha=0.3)
ax.set_title("Polynomial: y = 2x^2 - 3x + 1 (degree 2)")
save(fig, "fig_math_polynomials_graph.svg")

# 5. Variation.
fig, axes = plt.subplots(1, 2, figsize=(8, 3.5))
x = np.linspace(0, 5, 100)
axes[0].plot(x, 2 * x, color="#16a34a", linewidth=2)
axes[0].set_title("Direct: y=2x")
axes[0].grid(True, alpha=0.3)
axes[0].set_xlabel("x")
axes[0].set_ylabel("y")
x2 = np.linspace(0.2, 5, 100)
axes[1].plot(x2, 10 / x2, color="#dc2626", linewidth=2)
axes[1].set_title("Inverse: y=10/x")
axes[1].grid(True, alpha=0.3)
axes[1].set_xlabel("x")
axes[1].set_ylabel("y")
fig.suptitle("Variation: Direct vs Inverse (k=10)")
save(fig, "fig_math_variation_graphs.svg")

# 6. Fractions pie.
fig, ax = plt.subplots(figsize=(3.5, 3.5))
ax.pie([3, 5], labels=["3/8", "5/8"], autopct="%1.0f%%", colors=["#2563eb", "#e5e7eb"], startangle=90, textprops={"fontsize": 10})
ax.set_title("Fraction 3/8 of a Whole")
save(fig, "fig_math_fractions_pie.svg")

print("done")
