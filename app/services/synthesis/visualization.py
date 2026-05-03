from __future__ import annotations

import base64
import io
import logging
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import json

logger = logging.getLogger(__name__)


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _safe_import_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcdefaults()
    return plt


# Static matplotlib charts (for PDF)

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
            reduced[:, 0], reduced[:, 1],
            c=labels, cmap="tab10",
            alpha=0.8, edgecolors="white", linewidths=0.5, s=80,
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
                ha="center", fontsize=9,
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

        ax.plot(years, counts, marker="o", linewidth=2.5, color="#14b8a6")
        ax.fill_between(years, counts, alpha=0.16, color="#14b8a6")

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

        labels = list(freq_data.keys())
        values = list(freq_data.values())

        if not any(values):
            return None

        fig, ax = plt.subplots(figsize=(8, 4))

        ax.bar(labels, values, color="#3b82f6")
        ax.set_title(title)
        ax.set_xlabel("Category")
        ax.set_ylabel("Frequency")
        ax.tick_params(axis='x', rotation=45)
        ax.grid(axis='y', alpha=0.3)

        fig.tight_layout()

        result = _fig_to_b64(fig)
        plt.close(fig)
        return result

    except Exception as exc:
        logger.warning("frequency_bar failed: %s", exc)
        return None
    if not freq_data:
        return None
    try:
        plt = _safe_import_matplotlib()
        from matplotlib.ticker import MaxNLocator

        sorted_items = sorted(freq_data.items(), key=lambda x: x[1], reverse=True)[:10]
        labels, values = zip(*sorted_items)
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(labels, values, color="#6366f1", edgecolor="white")
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xlabel("Item")
        ax.set_ylabel("Frequency")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        plt.xticks(rotation=45, ha='right')
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        result = _fig_to_b64(fig)
        plt.close(fig)
        return result
    except Exception as exc:
        logger.warning("%s static failed: %s", title, exc)
        return None


#Interactive Plotly charts (for frontend)

def make_plotly_frequency_bar(freq_data: Dict[str, int], title: str) -> Optional[dict]:
    if not freq_data:
        return None
    try:
        sorted_items = sorted(freq_data.items(), key=lambda x: x[1], reverse=True)[:10]
        labels, values = zip(*sorted_items)
        labels = labels[::-1]
        values = values[::-1]
        fig = go.Figure(data=[go.Bar(
            x=values, y=labels, orientation='h',
            marker_color='#6366f1', marker_line_color='white',
            marker_line_width=1.5, opacity=0.8,
        )])
        fig.update_layout(
            title={"text": title, "font": {"size": 20, "color": "#1e293b"}},
            xaxis_title="Frequency", yaxis_title="Item",
            template="plotly_white",
            margin=dict(l=40, r=40, t=60, b=40),
            hovermode="x unified",
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("%s plotly failed: %s", title, exc)
        return None




def make_plotly_research_intensity(papers: list[dict]) -> Optional[dict]:
  
    if not papers:
        return None
    try:
        years = [int(p.get("year")) for p in papers if p.get("year") and str(p.get("year")).isdigit()]
        if not years:
            return None
        min_year, max_year = min(years), max(years)
        all_years = list(range(min_year, max_year + 1))
        year_counts = Counter(years)
        counts = [year_counts[y] for y in all_years]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=all_years, y=counts,
            mode='lines+markers', name='Papers',
            line=dict(color='#6366f1', width=3),
            marker=dict(size=8, color='#4f46e5'),
            fill='tozeroy', fillcolor='rgba(99, 102, 241, 0.1)',
        ))
        fig.update_layout(
            title={"text": "Research Intensity Over Time", "font": {"size": 16}},
            xaxis=dict(title="Year", tickmode='linear'),
            yaxis=dict(title="Paper Count", rangemode='tozero'),
            template="plotly_white",
            height=250,
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("gap_evolution_chart failed: %s", exc)
        return None


def make_plotly_umap(
    reduced: np.ndarray,
    labels: np.ndarray,
    titles: list[str],
) -> Optional[dict]:
    if reduced is None or len(reduced) == 0:
        return None
    try:
        fig = px.scatter(
            x=reduced[:, 0], y=reduced[:, 1],
            color=labels.astype(str),
            hover_name=titles,
            title="Interactive Research Landscape",
            labels={'x': 'UMAP-1', 'y': 'UMAP-2', 'color': 'Cluster'},
            template="plotly_white",
            color_discrete_sequence=px.colors.qualitative.Safe,
        )
        fig.update_traces(marker=dict(size=10, opacity=0.7, line=dict(width=1, color='White')))
        fig.update_layout(
            dragmode='pan', hovermode='closest',
            margin=dict(l=0, r=0, t=60, b=0),
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("plotly_umap failed: %s", exc)
        return None


def make_plotly_cluster_distribution(
    labels: np.ndarray,
    cluster_themes: dict[int, dict],
) -> Optional[dict]:
    #Horizontal bar chart showing paper count per cluster,
   
    if labels is None or len(labels) == 0:
        return None
    try:
        from collections import Counter as _Counter
        label_counts = _Counter(int(l) for l in labels if l != -1)
        if not label_counts:
            return None

        cluster_ids = sorted(label_counts.keys())
        paper_counts = [label_counts[c] for c in cluster_ids]
        import textwrap
        theme_labels = []
        for c in cluster_ids:
            raw_label = cluster_themes.get(c, {}).get("theme_label", f"Cluster {c}")
            if len(raw_label) > 60:
                raw_label = raw_label[:57] + "..."
            theme_labels.append("<br>".join(textwrap.wrap(raw_label, width=35)))

        fig = go.Figure(data=[go.Bar(
            y=theme_labels,
            x=paper_counts,
            orientation='h',
            marker_color='#6366f1',
            marker_line_color='white',
            marker_line_width=1.5,
            opacity=0.85,
            text=paper_counts,
            textposition='auto',
            hovertemplate='<b>%{y}</b><br>Papers: %{x}<extra></extra>',
        )])
        fig.update_layout(
            title={"text": "Cluster Distribution by Theme", "font": {"size": 18}},
            xaxis_title="Number of Papers",
            yaxis_title="Cluster Theme",
            yaxis=dict(automargin=True),
            template="plotly_white",
            height=max(300, 80 * len(cluster_ids)),
            margin=dict(l=20, r=20, t=60, b=40),
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("plotly_cluster_distribution failed: %s", exc)
        return None


def make_plotly_gap_frequency(gaps: list) -> Optional[dict]:
    
    #Horizontal ranked bar chart of gap titles by confidence score.
    
    if not gaps:
        return None
    try:
        # Sort ascending so highest confidence is at top when rendered horizontally
        sorted_gaps = sorted(gaps, key=lambda g: g.confidence_score)
        import textwrap
        titles = [
            "<br>".join(textwrap.wrap(g.gap_title, width=40))
            for g in sorted_gaps
        ]
        scores = [float(g.confidence_score or 0.0) for g in sorted_gaps]
        gap_ids = [g.gap_id for g in sorted_gaps]

        # Purple gradient by score
        colors = ['#6366f1' if s >= 0.8 else '#a78bfa' if s >= 0.6 else '#c4b5fd' for s in scores]

        fig = go.Figure(data=[go.Bar(
            y=titles,
            x=scores,
            orientation='h',
            marker_color=colors,
            marker_line_color='white',
            marker_line_width=1,
            opacity=0.9,
            text=[f"{s:.3f}" for s in scores],
            textposition='auto',
            hovertemplate='<b>%{y}</b><br>Confidence: %{x:.3f}<extra></extra>',
            customdata=gap_ids,
        )])
        fig.update_layout(
            title={"text": "Research Gaps Ranked by Confidence", "font": {"size": 18}},
            xaxis=dict(title="Confidence Score", range=[0, 1.05]),
            yaxis_title="Gap Title",
            yaxis=dict(automargin=True),
            template="plotly_white",
            height=max(300, 70 * len(gaps)),
            margin=dict(l=20, r=20, t=60, b=40),
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("plotly_gap_frequency failed: %s", exc)
        return None


def make_paper_gap_mapping(
    papers: list[dict],
    gaps: list,
    labels: np.ndarray,
) -> Optional[dict]:
    """
    Heatmap showing which papers support which gaps.
    X axis: Gap IDs | Y axis: Paper titles (truncated) | Cell: 1 if paper supports gap.
    """
    if not papers or not gaps:
        return None
    try:
        # Build paper→cluster lookup from labels
        paper_cluster: dict[int, int] = {
            i: int(labels[i]) for i in range(len(labels)) if i < len(papers)
        }
        # Build gap→cluster lookup
        gap_clusters = {g.gap_id: g.cluster_id for g in gaps}

        import textwrap
        paper_titles = [
            "<br>".join(textwrap.wrap(p.get("title", f"Paper {i}"), width=70))
            for i, p in enumerate(papers)
        ]
        gap_ids = [g.gap_id for g in gaps]

        # Build z matrix
        z = []
        hover = []
        for i, paper in enumerate(papers):
            row = []
            hover_row = []
            cluster = paper_cluster.get(i, -1)
            for gap in gaps:
                # Paper supports gap if it's in the same cluster
                supports = 1 if cluster == gap.cluster_id else 0
                row.append(supports)
                year = paper.get("year", "N/A")
                cites = paper.get("citation_count", 0)
                full_title_hover = "<br>".join(textwrap.wrap(paper.get('title', ''), width=60))
                hover_row.append(
                    f"Paper: {full_title_hover}<br>"
                    f"Year: {year} | Citations: {cites}<br>"
                    f"Gap: {gap.gap_id}"
                )
            z.append(row)
            hover.append(hover_row)

        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=gap_ids,
            y=paper_titles,
            colorscale=[[0, "#f8fafc"], [1, "#6366f1"]],
            showscale=False,
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
            zmin=0, zmax=1,
        ))
        fig.update_layout(
            title={"text": "Paper-to-Gap Support Mapping", "font": {"size": 18}},
            xaxis=dict(title="Research Gap", tickangle=0),
            yaxis=dict(title="Paper", automargin=True, tickfont=dict(size=11)),
            template="plotly_white",
            height=max(400, 45 * len(papers)),
            margin=dict(l=20, r=20, t=60, b=60),
        )
        return json.loads(fig.to_json())
    except Exception as exc:
        logger.warning("paper_gap_mapping failed: %s", exc)
        return None


#Orchestrator

def generate_all_visualizations(
    reduced_2d: np.ndarray,
    labels: np.ndarray,
    papers: list[dict],
    gaps: list,
    pattern,
    cluster_themes: dict[int, dict] | None = None,
) -> dict:
    titles = [p.get("title", "") for p in papers]
    _themes = cluster_themes or {}

    return {
        
        "umap_scatter": make_umap_scatter(reduced_2d, labels, titles),
        "confidence_bars": make_confidence_bars(gaps),
        "year_distribution": make_year_distribution(papers),


"method_trends": make_method_trends(pattern.method_trend_by_year),
"dataset_frequency": make_frequency_bar(pattern.dataset_frequency, "Dataset Frequency"),
"metric_frequency": make_frequency_bar(pattern.metric_frequency, "Metric Frequency"),


"plotly_research_intensity": make_plotly_research_intensity(papers),
"plotly_umap": make_plotly_umap(reduced_2d, labels, titles),

"plotly_dataset_freq": make_plotly_frequency_bar(
    pattern.dataset_frequency,
    "Dataset Frequency"
),

"plotly_metric_freq": make_plotly_frequency_bar(
    pattern.metric_frequency,
    "Metric Frequency"
),

"plotly_cluster_distribution": make_plotly_cluster_distribution(labels, _themes),
"plotly_gap_frequency": make_plotly_gap_frequency(gaps),
    }
