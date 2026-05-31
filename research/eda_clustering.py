# -*- coding: utf-8 -*-
"""
eda_clustering.py — EDA clustering of branches to find pooled-forecast groups.

Sprint C8.1 (research, not a v-bump):
  per-cell forecast for May 2026 was 2.33× actual (921 vs 396), even after
  C8.0's event tagging + recency-weighting fixes. Hypothesis: per-cell
  modeling is too noisy because most cells are sparse (<6 months). If
  branches cluster into 2-3 functional groups, we could pool data within
  clusters → less noise per model.

This script runs two clustering passes:
  1. SHAPE clustering on z-scored series (size-independent — clusters by
     temporal pattern only).
  2. LOGSTD clustering on log-transformed standardized series (preserves
     both shape and relative magnitude).

And two windows:
  A. Full last-24-months (Sep 2024 – Aug 2026 or whatever the data goes
     up to) — includes Roar of Lion war crash.
  B. Pre-war-only (Sep 2024 – Feb 2026, last 18 months before war).
     Reveals "routine structure" without the war signal dominating.

Outputs (all written to research/output/, gitignored):
  - clusters_dendrogram.png       — hierarchical clustering visualization
  - per_branch_series.png         — z-scored series colored by cluster
  - cluster_war_response.png      — drop% and recovery slope per cluster
  - cluster_assignments.csv       — branch → cluster_id table
  - kmeans_silhouette.csv         — silhouette scores for each (track, k)

And a markdown summary written to ./RESEARCH_EDA_FINDINGS.md (root, gitignored).

Usage:
  python research/eda_clustering.py

No CLI args; everything driven by constants below.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure we can import from repo root when launched from research/
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # headless — write PNG, don't pop window
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from scipy.cluster.hierarchy import linkage, dendrogram, fcluster


def df_to_md(df: pd.DataFrame, index: bool = True) -> str:
    """Render a DataFrame as a simple Markdown table without requiring
    the `tabulate` optional dependency. Numeric values are rounded for
    readability via caller's df.round() before calling this."""
    cols = list(df.columns)
    if index:
        cols = [df.index.name or 'index'] + cols
    header = '| ' + ' | '.join(str(c) for c in cols) + ' |'
    sep = '|' + '|'.join(['---'] * len(cols)) + '|'
    rows = []
    for idx, row in df.iterrows():
        cells = []
        if index:
            cells.append(str(idx))
        for c in df.columns:
            v = row[c]
            if isinstance(v, float):
                if pd.isna(v):
                    cells.append('')
                else:
                    cells.append(f"{v:g}")
            else:
                cells.append(str(v))
        rows.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join([header, sep] + rows)


# ---------- Configuration ----------
MIN_MONTHS = 24      # branches need at least this many months of history
MIN_TOTAL = 100      # AND at least this much total quantity (filters noise)
WAR_MONTHS = ('2026-02', '2026-03', '2026-04')   # months affected by Roar of Lion
PRE_WAR_END = '2026-01'                          # last full pre-war month
K_RANGE = range(2, 6)                            # try k=2..5

OUT_DIR = _REPO_ROOT / 'research' / 'output'
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = _REPO_ROOT / 'RESEARCH_EDA_FINDINGS.md'


# ---------- Helpers ----------
def load_history() -> pd.DataFrame:
    """Pull forecast_history once. Returns df with columns
    branch, luggage_type, year_month, quantity."""
    from forecast_db import ForecastDB
    fdb = ForecastDB()
    df = fdb.get_history()
    df['year_month'] = df['year_month'].astype(str)
    return df


def pick_qualified_branches(hist: pd.DataFrame) -> list[str]:
    """Branches with enough history and volume to cluster meaningfully."""
    months_per_branch = hist.groupby('branch')['year_month'].nunique()
    qty_per_branch = hist.groupby('branch')['quantity'].sum()
    qualified = months_per_branch[
        (months_per_branch >= MIN_MONTHS) & (qty_per_branch.reindex(months_per_branch.index, fill_value=0) >= MIN_TOTAL)
    ].index.tolist()
    return sorted(qualified, key=lambda b: -qty_per_branch.get(b, 0))


def build_series_matrix(hist: pd.DataFrame, branches: list[str],
                        months: list[str]) -> np.ndarray:
    """Returns shape (n_branches, n_months) — zero-filled for missing."""
    rows = []
    for b in branches:
        sub = hist[hist['branch'] == b].groupby('year_month')['quantity'].sum()
        s = pd.Series(0.0, index=months)
        common = [m for m in months if m in sub.index]
        s.loc[common] = sub.loc[common].astype(float)
        rows.append(s.values)
    return np.array(rows, dtype=float)


def zscore_per_row(X: np.ndarray) -> np.ndarray:
    """Z-score per row — same shape, but each row centered + scaled."""
    mu = X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1, keepdims=True) + 1e-9
    return (X - mu) / sd


def best_k_by_silhouette(X: np.ndarray, k_range=K_RANGE) -> tuple[int, dict]:
    """Run KMeans for each k; return best k by silhouette, plus all scores."""
    scores = {}
    for k in k_range:
        if k >= X.shape[0]:
            continue
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        try:
            sil = silhouette_score(X, labels)
        except ValueError:
            sil = -1.0
        scores[k] = {'silhouette': float(sil), 'labels': labels, 'model': km}
    if not scores:
        return -1, {}
    best = max(scores, key=lambda k: scores[k]['silhouette'])
    return best, scores


def war_response_stats(hist: pd.DataFrame, branches: list[str],
                       cluster_labels: dict[str, int]) -> pd.DataFrame:
    """For each cluster, compute pre-war mean, war-trough mean, and recovery
    slope (Apr→May if data, else just drop%)."""
    pre_war_window = ['2025-09', '2025-10', '2025-11', '2025-12', '2026-01']
    war_window = list(WAR_MONTHS)
    rows = []
    for b in branches:
        sub = hist[hist['branch'] == b].groupby('year_month')['quantity'].sum()
        pre = sub.reindex(pre_war_window).fillna(0).mean()
        war = sub.reindex(war_window).fillna(0).mean()
        drop_pct = (1 - war / max(pre, 0.1)) * 100 if pre > 0 else None
        rows.append({
            'branch': b,
            'cluster': cluster_labels.get(b, -1),
            'pre_war_mean': pre,
            'war_trough_mean': war,
            'drop_pct': drop_pct,
        })
    return pd.DataFrame(rows)


# ---------- Plots ----------
def plot_dendrogram(X_shape: np.ndarray, branches: list[str], out: Path):
    Z = linkage(X_shape, method='ward')
    fig, ax = plt.subplots(figsize=(11, 6))
    dendrogram(Z, labels=branches, ax=ax, leaf_rotation=45)
    ax.set_title("Hierarchical clustering (Ward, z-scored series, last 24 months)")
    ax.set_ylabel("Distance")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


def plot_series_by_cluster(series_matrix: np.ndarray, months: list[str],
                            branches: list[str], labels: np.ndarray,
                            out: Path, title: str):
    """One subplot per cluster; each shows z-scored series of member branches."""
    X_z = zscore_per_row(series_matrix)
    n_clusters = int(labels.max()) + 1
    fig, axes = plt.subplots(n_clusters, 1, figsize=(11, 3 * n_clusters), sharex=True)
    if n_clusters == 1:
        axes = [axes]
    for c in range(n_clusters):
        ax = axes[c]
        members = [branches[i] for i in range(len(branches)) if labels[i] == c]
        for i in range(len(branches)):
            if labels[i] == c:
                ax.plot(months, X_z[i], alpha=0.55, label=branches[i])
        ax.set_title(f"Cluster {c} (n={len(members)}): {', '.join(members)}")
        ax.set_ylabel("z-score")
        ax.grid(alpha=0.3)
        ax.axhline(0, color='gray', lw=0.5)
        ax.legend(fontsize=8, loc='upper right', ncol=2)
    axes[-1].set_xlabel("year_month")
    plt.setp(axes[-1].get_xticklabels(), rotation=45, ha='right')
    fig.suptitle(title, y=1.005, fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(out, dpi=120, bbox_inches='tight')
    plt.close()


def plot_war_response(stats_df: pd.DataFrame, out: Path):
    """Bar chart: per-cluster mean drop%."""
    g = stats_df.dropna(subset=['drop_pct']).groupby('cluster').agg(
        mean_drop=('drop_pct', 'mean'),
        std_drop=('drop_pct', 'std'),
        n_branches=('branch', 'count'),
    ).reset_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    x = g['cluster'].astype(str)
    bars = ax.bar(x, g['mean_drop'], yerr=g['std_drop'].fillna(0),
                  capsize=4, color='steelblue', alpha=0.8)
    for bar, n in zip(bars, g['n_branches']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"n={n}", ha='center', fontsize=10)
    ax.set_title("Mean war-period drop % per cluster (Mar-Apr 2026 vs Sep 2025 - Jan 2026)")
    ax.set_ylabel("Drop % (war_mean / pre_war_mean)")
    ax.set_xlabel("Cluster")
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


# ---------- Main ----------
def main():
    print("== Sprint C8.1: EDA Clustering ==")
    hist = load_history()
    print(f"Loaded {len(hist)} rows of forecast_history.")

    branches = pick_qualified_branches(hist)
    print(f"Qualified branches ({len(branches)}): {branches}")
    if len(branches) < 4:
        print("ABORT: too few branches to cluster.")
        return

    all_months = sorted(hist['year_month'].unique())

    # Two windows
    last_24 = all_months[-24:]
    pre_war_18 = [m for m in all_months if m <= PRE_WAR_END][-18:]

    X_24 = build_series_matrix(hist, branches, last_24)
    X_18 = build_series_matrix(hist, branches, pre_war_18)

    # Two normalizations × two windows = 4 tracks
    tracks = {
        'shape_24m_with_war':   zscore_per_row(X_24),
        'shape_18m_pre_war':    zscore_per_row(X_18),
        'logstd_24m_with_war':  StandardScaler().fit_transform(np.log1p(X_24)),
        'logstd_18m_pre_war':   StandardScaler().fit_transform(np.log1p(X_18)),
    }

    # K-Means per track
    all_results = {}
    sil_rows = []
    for track, X_in in tracks.items():
        best_k, scores = best_k_by_silhouette(X_in)
        all_results[track] = (best_k, scores)
        print(f"  {track}: best k={best_k}, sil={scores[best_k]['silhouette']:.3f}")
        for k, info in scores.items():
            sil_rows.append({
                'track': track, 'k': k,
                'silhouette': info['silhouette'],
            })
    pd.DataFrame(sil_rows).to_csv(OUT_DIR / 'kmeans_silhouette.csv', index=False)

    # Pick the best track overall
    track_best = max(all_results, key=lambda t:
                     all_results[t][1][all_results[t][0]]['silhouette'])
    best_k = all_results[track_best][0]
    best_labels = all_results[track_best][1][best_k]['labels']
    print(f"\nBest overall: track={track_best}, k={best_k}, "
          f"sil={all_results[track_best][1][best_k]['silhouette']:.3f}")

    # Choose months matching the best track
    months_used = last_24 if '24m' in track_best else pre_war_18
    X_used = X_24 if '24m' in track_best else X_18

    # Dendrogram (always on shape_24m for visual consistency)
    plot_dendrogram(zscore_per_row(X_24), branches, OUT_DIR / 'clusters_dendrogram.png')

    # Series by cluster
    plot_series_by_cluster(
        X_used, months_used, branches, best_labels,
        OUT_DIR / 'per_branch_series.png',
        title=f"Branches grouped by cluster — track={track_best}, k={best_k}",
    )

    # War response analysis (uses pre-war and war windows from ALL data)
    cluster_map = {b: int(best_labels[i]) for i, b in enumerate(branches)}
    stats = war_response_stats(hist, branches, cluster_map)
    stats.to_csv(OUT_DIR / 'cluster_assignments.csv', index=False)
    plot_war_response(stats, OUT_DIR / 'cluster_war_response.png')

    # ----- Write findings report -----
    write_report(
        branches=branches,
        track_best=track_best,
        best_k=best_k,
        all_results=all_results,
        cluster_map=cluster_map,
        stats=stats,
        sil_rows=sil_rows,
    )
    print(f"\nReport written: {REPORT_PATH}")
    print(f"Plots in: {OUT_DIR}")


def write_report(branches, track_best, best_k, all_results, cluster_map,
                 stats, sil_rows):
    """Markdown summary of findings."""
    best_sil = all_results[track_best][1][best_k]['silhouette']

    # Cluster-level summary
    cluster_summary = stats.groupby('cluster').agg(
        n_branches=('branch', 'count'),
        members=('branch', lambda s: ', '.join(map(str, s))),
        avg_pre_war=('pre_war_mean', 'mean'),
        avg_war_trough=('war_trough_mean', 'mean'),
        avg_drop_pct=('drop_pct', 'mean'),
        std_drop_pct=('drop_pct', 'std'),
    ).reset_index()

    # Recommendation logic
    if best_sil > 0.4:
        verdict = "**Clusters are well-separated**. Recommend building a pooled-forecast model per cluster."
    elif best_sil > 0.25:
        verdict = ("**Weak clustering signal**. Some structure exists but isn't clean. "
                   "Consider hierarchical pooling (global mean + branch effect) rather than hard clusters.")
    else:
        verdict = ("**No clustering signal**. Branches are too heterogeneous or too noisy. "
                   "Recommend trying a different approach (per-branch autoencoder, "
                   "or focusing on regime-aware models with explicit event handling).")

    # Differential war response (does any cluster react differently?)
    drop_spread = cluster_summary['avg_drop_pct'].max() - cluster_summary['avg_drop_pct'].min()
    if drop_spread > 20:
        differential = (f"**Differential war response detected**: clusters react differently "
                        f"(spread = {drop_spread:.0f} percentage points). "
                        f"This is exploitable — different clusters may need different "
                        f"regime-adjustment factors.")
    else:
        differential = (f"**Homogeneous war response** (spread = {drop_spread:.0f} pp). "
                        f"All clusters crashed similarly during Roar of Lion. "
                        f"Implication: clustering won't help isolate war response; "
                        f"the war is a global event, not a cluster-specific one.")

    lines = [
        "# Sprint C8.1 — EDA Clustering Findings",
        "",
        "**Generated**: from `research/eda_clustering.py`. **Not in git.**",
        "",
        "## TL;DR",
        "",
        f"- **Branches analyzed**: {len(branches)} (need 24+ months of data + 100+ total qty)",
        f"- **Best track**: `{track_best}`, k={best_k}",
        f"- **Silhouette score**: {best_sil:.3f}",
        f"- **Verdict**: {verdict}",
        f"- {differential}",
        "",
        "## Silhouette scores (all tracks × k)",
        "",
        df_to_md(pd.DataFrame(sil_rows).pivot_table(
            index='track', columns='k', values='silhouette'
        ).round(3), index=True),
        "",
        "(Silhouette: 1.0 = perfect separation, 0.0 = ambiguous, -1.0 = wrong assignments. "
        "Useful threshold for production: ≥0.4 = solid, 0.25-0.4 = weak, <0.25 = no signal.)",
        "",
        "## Cluster membership (best track)",
        "",
        df_to_md(cluster_summary.round(1), index=False),
        "",
        "## Per-branch details",
        "",
        df_to_md(stats.sort_values(['cluster', 'pre_war_mean'],
                                     ascending=[True, False]).round(1),
                  index=False),
        "",
        "## Plots",
        "",
        "- `research/output/clusters_dendrogram.png` — hierarchical clustering view",
        "- `research/output/per_branch_series.png` — z-scored series per cluster",
        "- `research/output/cluster_war_response.png` — drop % per cluster",
        "- `research/output/cluster_assignments.csv` — raw table",
        "- `research/output/kmeans_silhouette.csv` — all (track, k) scores",
        "",
        "## Recommendation for Sprint C8.2",
        "",
    ]

    if best_sil > 0.4:
        lines.extend([
            "### Build a pooled-forecast model per cluster",
            "",
            "Each cluster gets ONE model trained on all member branches' data,",
            "with `branch_id` as a one-hot feature. This pools data across",
            "sparse cells. Estimated training data per model:",
            "",
        ])
        for _, row in cluster_summary.iterrows():
            n = int(row['n_branches'])
            lines.append(f"- Cluster {int(row['cluster'])}: ~{n * 24} branch-months "
                         f"(vs ~24 per single branch)")
        lines.append("")
    elif best_sil > 0.25:
        lines.extend([
            "### Try hierarchical pooling (global model with branch effects)",
            "",
            "Clusters aren't clean enough to split forecasts cleanly. Instead:",
            "1. Train one global model on all branches, with `branch_id` as feature.",
            "2. Add a small `branch_effect` term that adjusts the global forecast",
            "   based on each branch's historical deviation.",
            "",
            "This is what mixed-effects regression does. Easier to start with",
            "scikit-learn's LinearRegression + branch dummies and a regularizer.",
            "",
        ])
    else:
        lines.extend([
            "### Different approach needed",
            "",
            "Clustering didn't find usable structure. Candidates for C8.2:",
            "",
            "1. **Autoencoder per top branch** (originally option 2 in this sprint).",
            "   Train a small AE on each big branch's series; reconstruction error",
            "   tells us when 'this month is unusual'. Useful for regime detection.",
            "",
            "2. **Explicit regime models**. Maintain 2-3 forecast models, each",
            "   trained on a specific regime (routine / military_op / war).",
            "   At forecast time, blend based on current/expected events.",
            "",
            "3. **Look at the data differently**. The forecast misses we've seen",
            "   may have a single cause we haven't named — e.g. weekly seasonality,",
            "   day-of-week effects, customer-specific patterns. Worth a manual",
            "   exploration before more ML.",
            "",
        ])

    lines.extend([
        "## Caveats",
        "",
        "- **Sample size is tiny**: 13 branches × 24 months = 312 data points.",
        "  Statistical conclusions are suggestive, not definitive.",
        "- **War dominates the signal**: Mar-Apr 2026 crashes are visible in",
        "  every branch. The `*_18m_pre_war` tracks are the cleaner test for",
        "  routine-period structure.",
        "- **No DTW**: clustering uses Euclidean distance on normalized series.",
        "  For 24-month monthly data this is adequate; DTW would matter for",
        "  higher-frequency data with phase shifts.",
        "- **No causal inference**: clustering finds associations, not causes.",
        "  Even if clusters separate cleanly, we don't know WHY without more work.",
        "",
    ])

    with REPORT_PATH.open('w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    main()
