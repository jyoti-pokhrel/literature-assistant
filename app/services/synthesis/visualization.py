from __future__ import annotations

import base64
import io
import logging
from collections import Counter
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _safe_import_matplotlib():
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend — safe for server use
    import matplotlib.pyplot as plt
    # Reset any params to default
    matplotlib.rcdefaults()
    return plt

# Individual chart generators

def make_umap_scatter(
    reduced: np.ndarray,
    labels: np.ndarray,
    titles: Optional[List[str]] = None,
) -> Optional[str]:
    if reduced is None or len(reduced) == 0:
        return None
    try:
        plt = _safe_import_matplotlib()
        fig, ax = plt.subplots(figsize=(7, 5))
        scatter = ax.scatter(
            reduced[:, 0],
            reduced[:, 1],
            c=labels,
            cmap="tab10",
            alpha=0.8,
            edgecolors="white",
            linewidths=0.5,
            s=80,
        )
        fig.colorbar(scatter, ax=ax, label="Cluster")
        ax.set_title("Paper Cluster Map (UMAP)", fontsize=13, fontweight="bold")
        ax.set_xlabel("UMAP-1")
        ax.set_ylabel("UMAP-2")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("umap_scatter failed: %s", exc)
        return None


def make_confidence_bars(gaps: list) -> Optional[str]:
    if not gaps:
        return None
    try:
        plt = _safe_import_matplotlib()
        labels = [g.gap_id for g in gaps]
        scores = [g.confidence_score for g in gaps]
        colors = ["#6366f1" if s >= 0.8 else "#a78bfa" if s >= 0.6 else "#c4b5fd" for s in scores]
        
        # Switched to vertical bar chart
        fig, ax = plt.subplots(figsize=(max(5, len(gaps) * 1.2), 5))
        bars = ax.bar(labels, scores, color=colors, edgecolor="white", width=0.6)
        
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("Confidence Score")
        ax.set_xlabel("Research Gap ID")
        ax.set_title("Research Gap Confidence Scores", fontsize=13, fontweight="bold")
        
        for bar, score in zip(bars, scores):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{score:.2f}",
                ha="center",
                fontsize=9,
            )
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("confidence_bars failed: %s", exc)
        return None


def make_year_distribution(papers: list[dict]) -> Optional[str]:
    if not papers:
        return None
    try:
        plt = _safe_import_matplotlib()
        from matplotlib.ticker import MaxNLocator
        
        years = [int(p.get("year")) for p in papers if p.get("year") and str(p.get("year")).isdigit()]
        if not years:
            return None
        counter = Counter(years)
        sorted_years = sorted(counter.keys())
        counts = [counter[y] for y in sorted_years]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar([str(y) for y in sorted_years], counts, color="#6366f1", edgecolor="white")
        ax.set_title("Papers per Year", fontsize=13, fontweight="bold")
        ax.set_xlabel("Year")
        ax.set_ylabel("Count")
        
        # Force Y-axis to be integers only
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("year_distribution failed: %s", exc)
        return None


def make_method_trends(method_trend_by_year: Dict[str, List[str]]) -> Optional[str]:
    if not method_trend_by_year:
        return None
    try:
        plt = _safe_import_matplotlib()
        years = sorted(method_trend_by_year.keys())
        counts = [len(method_trend_by_year.get(year, [])) for year in years]
        if not any(counts):
            return None

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(years, counts, color="#14b8a6", linewidth=2.5, marker="o")
        ax.fill_between(years, counts, color="#14b8a6", alpha=0.16)
        ax.set_title("Method Mentions by Year", fontsize=13, fontweight="bold")
        ax.set_xlabel("Year")
        ax.set_ylabel("Method mentions")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("method_trends failed: %s", exc)
        return None


def make_frequency_bar(freq_data: Dict[str, int], title: str) -> Optional[str]:
    if not freq_data:
        return None
    try:
        plt = _safe_import_matplotlib()
        from matplotlib.ticker import MaxNLocator
        
        # Sort by frequency descending and take top 10
        sorted_items = sorted(freq_data.items(), key=lambda x: x[1], reverse=True)[:10]
        labels, values = zip(*sorted_items)
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(labels, values, color="#6366f1", edgecolor="white")
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xlabel("Item")
        ax.set_ylabel("Frequency")
        
        # Force Y-axis to be integers only
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        
        plt.xticks(rotation=45, ha='right')
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("%s failed: %s", title, exc)
        return None

# Orchestrating function

def generate_all_visualizations(
    reduced: np.ndarray,
    labels: np.ndarray,
    papers: list[dict],
    gaps: list,
    pattern,
) -> dict:

    titles = [p.get("title", "") for p in papers]
    return {
        "umap_scatter": make_umap_scatter(reduced, labels, titles),
        "confidence_bars": make_confidence_bars(gaps),
        "year_distribution": make_year_distribution(papers),
        "method_trends": make_method_trends(pattern.method_trend_by_year),
        "dataset_frequency": make_frequency_bar(pattern.dataset_frequency, "Dataset Frequency"),
        "metric_frequency": make_frequency_bar(pattern.metric_frequency, "Metric Frequency"),
    }
