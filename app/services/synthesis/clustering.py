from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _umap_reduce(
    embeddings: np.ndarray, n_components: int, n_neighbors: int
) -> np.ndarray:
    # Run a single UMAP reduction to `n_components` dimensions.

    import warnings
    import umap  # type: ignore[import]

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=n_neighbors,
            min_dist=0.05,  # tighter clusters → HDBSCAN finds more of them
            random_state=42,
            n_jobs=1,
            low_memory=True,
        )
        return reducer.fit_transform(embeddings).astype(np.float32)


def _pca_reduce(embeddings: np.ndarray, n_components: int) -> np.ndarray:
    from sklearn.decomposition import PCA

    n_comp = min(n_components, embeddings.shape[0], embeddings.shape[1])
    pca = PCA(n_components=n_comp, random_state=42)
    reduced = pca.fit_transform(embeddings).astype(np.float32)
    if reduced.shape[1] < n_components:
        reduced = np.pad(reduced, ((0, 0), (0, n_components - reduced.shape[1])))
    return reduced


def _hdbscan_cluster(
    reduced: np.ndarray, min_cluster_size: int
) -> Tuple[np.ndarray, float]:
    import hdbscan  # type: ignore[import]

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,  # less strict density → more clusters found in sparse sets
        gen_min_span_tree=True,  # required for validity score
    )
    labels = clusterer.fit_predict(reduced).astype(int)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

    # Extract validity score (DBCV)
    validity = 0.0
    if n_clusters > 0:
        try:
            validity = float(clusterer.relative_validity_)
        except Exception:
            pass

    logger.info(
        "HDBSCAN produced %d clusters with DBCV score %.3f.", n_clusters, validity
    )
    return labels, validity


def _dbscan_cluster(reduced: np.ndarray) -> np.ndarray:
    from sklearn.cluster import DBSCAN

    clusterer = DBSCAN(eps=0.5, min_samples=2, metric="euclidean")
    labels = clusterer.fit_predict(reduced).astype(int)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    logger.info("DBSCAN fallback produced %d clusters.", n_clusters)
    return labels


def reduce_and_cluster(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int = 2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:

    n = len(embeddings)

    if n == 0:
        return (
            np.empty((0, 2), dtype=np.float32),
            np.empty((0, 5), dtype=np.float32),
            np.empty(0, dtype=int),
            0.0,
        )

    if n == 1:
        return (
            np.zeros((1, 2), dtype=np.float32),
            np.zeros((1, 5), dtype=np.float32),
            np.array([0], dtype=int),
            0.0,
        )

    # makes UMAP use 75% of data as context → over-smooth blob → few clusters.
    # A local neighbourhood (≤15) reveals broader topological structure (fewer clusters).
    neighbors = min(15, n - 1)
    nd_components = min(5, n - 1)

    # We need at least 2 dimensions for visualization; run to max of the two
    target_dims = max(nd_components, 2)

    try:
        # Single UMAP call — halves the previous cost
        reduced_full = _umap_reduce(embeddings, target_dims, neighbors)
        reduced_2d = reduced_full[:, :2]
        reduced_nd = reduced_full[:, :nd_components]
        logger.info("UMAP %dD reduction complete (single pass).", target_dims)
    except Exception as exc:
        logger.warning("UMAP failed (%s); using PCA fallback.", exc)
        reduced_full = _pca_reduce(embeddings, n_components=target_dims)
        reduced_2d = reduced_full[:, :2]
        reduced_nd = reduced_full[:, :nd_components]

    # Clustering on the higher-dimensional space
    safe_min_cluster = max(2, min(min_cluster_size, n))

    # Calculate Cluster Accuracy
    cluster_accuracy = 0.0

    try:
        labels, hdbscan_validity = _hdbscan_cluster(reduced_nd, safe_min_cluster)
        cluster_accuracy = hdbscan_validity
    except Exception as exc:
        logger.warning("HDBSCAN failed (%s); trying DBSCAN fallback.", exc)
        labels = _dbscan_cluster(reduced_nd)

        # Fallback to Silhouette Score for non-HDBSCAN clusters
        from sklearn.metrics import silhouette_score

        valid_indices = labels != -1
        if sum(valid_indices) > 2 and len(set(labels[valid_indices])) > 1:
            try:
                cluster_accuracy = float(
                    silhouette_score(embeddings[valid_indices], labels[valid_indices])
                )
            except Exception:
                pass

    # If everything was noise, treat all as one cluster
    if all(lbl == -1 for lbl in labels):
        logger.info("All papers labeled as noise; treating as single cluster.")
        labels = np.zeros(n, dtype=int)
        cluster_accuracy = 0.0

    return reduced_2d, reduced_nd, labels, float(cluster_accuracy)
