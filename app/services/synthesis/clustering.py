from __future__ import annotations

import logging
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

def _kmeans_fallback(embeddings: np.ndarray, n_clusters: int = 3) -> np.ndarray:
    from sklearn.cluster import KMeans

    k = min(n_clusters, len(embeddings))
    if k < 2:
        return np.zeros(len(embeddings), dtype=int)
    km = KMeans(n_clusters=k, random_state=42, n_init="auto")
    return km.fit_predict(embeddings)


def reduce_and_cluster(
    embeddings: np.ndarray,
    *,
    n_components: int = 2,
    min_cluster_size: int = 2,
) -> Tuple[np.ndarray, np.ndarray]:
    
    n = len(embeddings)
    if n == 0:
        return np.empty((0, 2), dtype=np.float32), np.empty(0, dtype=int)

    if n == 1:
        return np.zeros((1, 2), dtype=np.float32), np.array([0])

    #UMAP dimensionality reduction
    try:
        import umap 

        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=min(15, n - 1),
            min_dist=0.1,
            random_state=42,
        )
        reduced = reducer.fit_transform(embeddings).astype(np.float32)
        logger.info("UMAP reduction complete (%d → %d dims).", embeddings.shape[1], n_components)
    except Exception as exc:
        logger.warning("UMAP failed (%s); using PCA fallback.", exc)
        from sklearn.decomposition import PCA

        pca = PCA(n_components=min(n_components, n, embeddings.shape[1]))
        reduced = pca.fit_transform(embeddings).astype(np.float32)
        # Pad to 2 columns if needed
        if reduced.shape[1] < 2:
            reduced = np.pad(reduced, ((0, 0), (0, 2 - reduced.shape[1])))

    #HDBSCAN clustering
    try:
        import hdbscan  

        clusterer = hdbscan.HDBSCAN(min_cluster_size=min(min_cluster_size, n))
        labels = clusterer.fit_predict(reduced).astype(int)
        logger.info("HDBSCAN produced %d clusters.", len(set(labels)) - (1 if -1 in labels else 0))
    except Exception as exc:
        logger.warning("HDBSCAN failed (%s); using KMeans fallback.", exc)
        labels = _kmeans_fallback(reduced)

    return reduced, labels
