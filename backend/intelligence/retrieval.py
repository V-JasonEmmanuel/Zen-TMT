"""Local vector search (FAISS when installed, NumPy otherwise)."""
from __future__ import annotations

import numpy as np


class VectorIndex:
    def __init__(self, vectors: np.ndarray):
        self.vectors = np.ascontiguousarray(vectors.astype(np.float32))
        self._faiss = None
        if len(self.vectors) > 256:  # brute force NumPy is faster below this size
            try:
                import faiss

                idx = faiss.IndexFlatIP(self.vectors.shape[1])
                idx.add(self.vectors)
                self._faiss = idx
            except Exception:
                self._faiss = None

    def similarities(self, query: np.ndarray) -> np.ndarray:
        """Cosine similarity of every stored vector to `query` (vectors are normalised)."""
        if len(self.vectors) == 0:
            return np.zeros(0, np.float32)
        return self.vectors @ query.astype(np.float32).reshape(-1)

    def search(self, query: np.ndarray, k: int = 10) -> list[tuple[int, float]]:
        k = min(k, len(self.vectors))
        if k == 0:
            return []
        if self._faiss is not None:
            d, i = self._faiss.search(query.reshape(1, -1).astype(np.float32), k)
            return [(int(a), float(b)) for a, b in zip(i[0], d[0]) if a >= 0]
        sims = self.similarities(query)
        top = np.argsort(-sims)[:k]
        return [(int(j), float(sims[j])) for j in top]
