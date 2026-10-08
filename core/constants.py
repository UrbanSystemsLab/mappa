"""Fixed facts that more than one part of the system must agree on.

Not configuration - these do not change between deployments, and changing one
means changing data too. They are stated once because two parts disagreeing
about any of them is silent: a second embedding model still returns 384 numbers,
and the search still returns its nearest rows - the wrong ones.
"""

# The embedding model for questions, documents and layers, and its vector width.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

# The zoom range tiles are served and baked for.
TILE_MIN_ZOOM = 4
TILE_MAX_ZOOM = 14

# Below this similarity, the closest passage is not about the question.
MIN_RELEVANCE = 0.25

# Tables named layer_* that hold no map data.
NOT_LAYER_TABLES = frozenset({"layer_registry", "layer_inventory", "layer_roles"})
