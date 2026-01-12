# Vectl Cluster Map Serialization Bug

## Summary

The vectl vector store has a bug where the cluster map is not correctly persisted/restored across store reopens. This causes similarity search to fail because vectors cannot be found in their assigned clusters.

## Reproduction Steps

```bash
# 1. Build pattern database with embeddings
source ~/.pyenv/versions/tinymachines/bin/activate
rm ~/.cbos/patterns.db ~/.cbos/vectors.bin
python -m orchestrator.cli build

# 2. Observe vectors stored in cluster 49
# Log output during build:
# 2026-01-10 15:30:04 [DEBUG] Stored vector 1 in cluster 49
# 2026-01-10 15:30:04 [DEBUG] Stored vector 2 in cluster 49
# ... all 46 vectors go to cluster 49

# 3. Run similarity query
python -m orchestrator.cli query "Should I proceed?"

# 4. Observe cluster map shows 0 clusters
# Log output during query:
# 2026-01-10 15:30:09 [DEBUG] Read cluster map: 0 clusters   <-- BUG
# 2026-01-10 15:30:09 [DEBUG] Read vector map: 46 vectors
# 2026-01-10 15:30:09 [DEBUG] Searching in cluster 17        <-- Wrong clusters
# 2026-01-10 15:30:09 [DEBUG] Searching in cluster 7
# 2026-01-10 15:30:09 [DEBUG] Searching in cluster 6
# 2026-01-10 15:30:09 [INFO] Processed 0 vectors from 3 clusters
```

## Expected Behavior

1. During build: Vectors are assigned to clusters based on K-means centroids
2. Cluster map (centroids + cluster assignments) is written to disk
3. On reopen: Cluster map is read back with correct centroids
4. During query: Search uses same centroids to find relevant clusters
5. Vectors in those clusters are compared for similarity

## Actual Behavior

1. During build: All vectors assigned to cluster 49 (single cluster, likely due to uninitialized centroids)
2. Cluster map written shows "50 clusters" but data is not persisted correctly
3. On reopen: Cluster map shows "0 clusters"
4. During query: K-means assigns query to different clusters (17, 7, 6) based on fresh random centroids
5. No vectors found because they were stored in cluster 49

## Root Cause Analysis

### Location: `vectl/src/vector_cluster_store.cpp`

#### Issue 1: Cluster Map Write (lines ~93-97)
```cpp
// Write empty maps
if (!writeClusterMap() || !writeVectorMap()) {
    logger_.error("Failed to write store metadata");
    ...
}
```

The `writeClusterMap()` function may not be serializing the centroid vectors correctly.

#### Issue 2: Cluster Map Read
```cpp
if (!readClusterMap() || !readVectorMap()) {
    logger_.error("Failed to read store metadata");
    ...
}
```

The `readClusterMap()` function returns success but loads 0 clusters, suggesting:
- Centroids are not being written to the correct offset
- Or the cluster count is not being persisted in the header
- Or the centroid data format doesn't match read expectations

#### Issue 3: K-means Initialization
All vectors going to cluster 49 during initial build suggests the K-means centroids are not properly initialized before vector insertion. The clustering strategy should:
1. Initialize with random or spread-out centroids
2. Update centroids as vectors are added
3. Persist final centroids to disk

## Files to Investigate

1. `vectl/src/vector_cluster_store.cpp`
   - `writeClusterMap()` - How are centroids serialized?
   - `readClusterMap()` - How are centroids deserialized?
   - Layout constants: `cluster_map_offset_`, region sizes

2. `vectl/src/kmeans_clustering.cpp`
   - `initialize()` - How are initial centroids set?
   - `addVector()` - Does it update centroids?
   - Serialization of centroid state

3. `vectl/src/vector_cluster_store.h`
   - Cluster map data structures
   - Header format (does it include cluster count?)

## Suggested Fix Approach

1. **Add cluster count to header**: Ensure the number of active clusters is stored in the store header and restored on load.

2. **Serialize centroids properly**: Each centroid is a 768-dimensional vector. Ensure:
   ```cpp
   // Write format per cluster:
   // - cluster_id (4 bytes)
   // - vector_count (4 bytes)
   // - centroid[768] (768 * 4 = 3072 bytes)
   ```

3. **Initialize centroids on first vector**: If no centroids exist, the first N vectors should seed the initial centroids.

4. **Update centroids incrementally**: As vectors are added, update the relevant cluster's centroid (running average).

5. **Add validation**: On load, verify cluster count > 0 before attempting similarity search.

## Workaround

Until fixed, similarity search is broken. Text search via SQLite still works:
```bash
python -m orchestrator.cli search "keyword"
```

## Test Case

```python
# test_cluster_persistence.py
from vector_store import create_store
import numpy as np

# Create store and add vectors
store = create_store("/tmp/test_vectors.bin", vector_dim=768, num_clusters=10)
for i in range(100):
    vec = np.random.randn(768).astype(np.float32).tolist()
    store.store_vector(i, vec, f"vector_{i}")

# Close and reopen
del store
store = create_store("/tmp/test_vectors.bin", vector_dim=768, num_clusters=10)

# Query should find vectors
query = np.random.randn(768).astype(np.float32).tolist()
results = store.find_similar_vectors(query, k=10)

assert len(results) > 0, "Similarity search should return results after reopen"
print(f"Found {len(results)} similar vectors")
```

## Priority

**High** - This bug makes the similarity search feature completely non-functional after store reopen, which is the core use case for vectl.
