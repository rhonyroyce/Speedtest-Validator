"""GPU utilities — RAPIDS cuDF/cuML acceleration with pandas/sklearn fallback.

Both Ollama host GPUs are NVIDIA, so RAPIDS can accelerate data processing
when available. This module auto-detects RAPIDS and falls back gracefully.

Usage:
    from code.utils.gpu_utils import read_csv, to_pandas, gpu_info, GPU_BACKEND
"""

# Attempt RAPIDS import — graceful fallback to pandas/sklearn
try:
    import cudf as pd_engine
    import cuml  # noqa: F401
    RAPIDS_AVAILABLE = True
    GPU_BACKEND = "RAPIDS cuDF"
except ImportError:
    import pandas as pd_engine
    RAPIDS_AVAILABLE = False
    GPU_BACKEND = "pandas (CPU)"


def get_dataframe_engine():
    """Return cudf if RAPIDS available, else pandas."""
    return pd_engine


def read_csv(path: str, **kwargs):
    """GPU-accelerated CSV read if RAPIDS available."""
    return pd_engine.read_csv(path, **kwargs)


def to_pandas(df):
    """Convert to pandas DataFrame (needed for libs that don't accept cuDF)."""
    if RAPIDS_AVAILABLE and hasattr(df, "to_pandas"):
        return df.to_pandas()
    return df


def gpu_info() -> dict:
    """Report GPU acceleration status."""
    info = {"rapids_available": RAPIDS_AVAILABLE, "backend": GPU_BACKEND}
    if RAPIDS_AVAILABLE:
        try:
            import cupy
            info["gpu_memory_total"] = f"{cupy.cuda.Device().mem_info[1] / 1e9:.1f} GB"
            info["gpu_memory_free"] = f"{cupy.cuda.Device().mem_info[0] / 1e9:.1f} GB"
        except Exception:
            pass
    return info


# --- cuML accelerated operations (drop-in sklearn replacements) ---


def cluster_kmeans(X, n_clusters=5, **kwargs):
    """KMeans clustering — cuML on GPU, sklearn on CPU."""
    if RAPIDS_AVAILABLE:
        from cuml.cluster import KMeans
    else:
        from sklearn.cluster import KMeans
    return KMeans(n_clusters=n_clusters, **kwargs).fit_predict(X)


def reduce_dimensions(X, n_components=2, method="umap", **kwargs):
    """Dimensionality reduction — cuML UMAP/PCA on GPU, sklearn on CPU."""
    if method == "umap":
        if RAPIDS_AVAILABLE:
            from cuml.manifold import UMAP
        else:
            try:
                from umap import UMAP
            except ImportError:
                from sklearn.decomposition import PCA as UMAP
                method = "pca"  # fallback
        return UMAP(n_components=n_components, **kwargs).fit_transform(X)
    else:
        if RAPIDS_AVAILABLE:
            from cuml.decomposition import PCA
        else:
            from sklearn.decomposition import PCA
        return PCA(n_components=n_components, **kwargs).fit_transform(X)


def nearest_neighbors(X, n_neighbors=5, **kwargs):
    """Nearest neighbors — cuML on GPU, sklearn on CPU."""
    if RAPIDS_AVAILABLE:
        from cuml.neighbors import NearestNeighbors
    else:
        from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=n_neighbors, **kwargs)
    nn.fit(X)
    return nn


def cosine_similarity_matrix(embeddings):
    """Compute cosine similarity matrix — GPU-accelerated if available."""
    if RAPIDS_AVAILABLE:
        import cupy as cp
        X = cp.array(embeddings)
        norms = cp.linalg.norm(X, axis=1, keepdims=True)
        X_norm = X / norms
        return cp.asnumpy(X_norm @ X_norm.T)
    else:
        import numpy as np
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        X_norm = embeddings / norms
        return X_norm @ X_norm.T
