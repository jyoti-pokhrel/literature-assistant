from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _umap_reduce(embeddings: np.ndarray, n_components: int, n_neighbors: int) -> np.ndarray:
    """Run UMAP reduction; raises on failure so caller can handle fallback."""
    import warnings
    import umap  # type: ignore[import]
    
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, message=".*n_jobs value 1 overridden.*")
        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=n_neighbors,
            min_dist=0.1,
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
    # Pad columns to requested size if needed
    if reduced.shape[1] < n_components:
        reduced = np.pad(reduced, ((0, 0), (0, n_components - reduced.shape[1])))
    return reduced


def _hdbscan_cluster(reduced: np.ndarray, min_cluster_size: int) -> np.ndarray:
    """HDBSCAN clustering; raises on failure."""
    import hdbscan  # type: ignore[import]
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size)
    labels = clusterer.fit_predict(reduced).astype(int)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    logger.info("HDBSCAN produced %d clusters.", n_clusters)
    return labels


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
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:

    n = len(embeddings)

    if n == 0:
        return (
            np.empty((0, 2), dtype=np.float32),
            np.empty((0, 5), dtype=np.float32),
            np.empty(0, dtype=int),
        )

    if n == 1:
        return (
            np.zeros((1, 2), dtype=np.float32),
            np.zeros((1, 5), dtype=np.float32),
            np.array([0], dtype=int),
        )

    neighbors = min(15, n - 1)

    #2D reduction for visualization
    try:
        reduced_2d = _umap_reduce(embeddings, n_components=2, n_neighbors=neighbors)
        logger.info("UMAP 2D reduction complete for visualization.")
    except Exception as exc:
        logger.warning("UMAP 2D failed (%s); using PCA fallback.", exc)
        reduced_2d = _pca_reduce(embeddings, n_components=2)

    nd_components = min(5, n - 1)
    try:
        reduced_nd = _umap_reduce(embeddings, n_components=nd_components, n_neighbors=neighbors)
        logger.info("UMAP %dD reduction complete for clustering.", nd_components)
    except Exception as exc:
        logger.warning("UMAP %dD failed (%s); using PCA fallback.", nd_components, exc)
        reduced_nd = _pca_reduce(embeddings, n_components=nd_components)

    #Clustering on high-dim space
    safe_min_cluster = max(2, min(min_cluster_size, n))

    try:
        labels = _hdbscan_cluster(reduced_nd, safe_min_cluster)
    except Exception as exc:
        logger.warning("HDBSCAN failed (%s); trying DBSCAN.", exc)
        labels = _dbscan_cluster(reduced_nd)

    # If everything was noise, put all in cluster 0
    if all(l == -1 for l in labels):
        logger.info("All papers labeled as noise; treating as single cluster.")
        labels = np.zeros(n, dtype=int)

    return reduced_2d, reduced_nd, labels
