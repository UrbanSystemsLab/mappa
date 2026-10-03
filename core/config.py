"""The settings that cross a module boundary.

The test for whether something belongs here is not "is it a constant". It is:
*would two parts of the system disagreeing about this be silent?* If yes, it has
to be stated once. If no, it belongs beside the code it tunes, where it can be
read in context - which is where `MIN_LAYER_SCORE`, the rate limits and the
simplification tolerances all still live, on purpose.
"""

from __future__ import annotations

import os

# Where everything reads and writes. Four modules each called os.environ.get for
# this, which meant four places to change and four chances to miss one.
DATABASE_URL = os.environ.get("DATABASE_URL")

# The embedding model, and the width of the vectors it makes.
#
# This was written out three times under three names - EMBEDDING_MODEL_NAME when
# a question is embedded, DEFAULT_MODEL when a document is, MODEL when a layer
# is. All three have to be the same model or the numbers mean different things,
# and nothing would have said so: a mismatched model still returns 384 floats,
# the database still stores them, and the search still returns its nearest rows.
# They would simply be the wrong rows, for every question, for as long as it took
# somebody to notice.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

# The zoom range the map is built for. The server stops making tiles above the
# maximum and the client over-zooms the last one; the baking pipeline has to stop
# at exactly the same place or it bakes tiles nothing asks for and misses the
# ones it does.
TILE_MIN_ZOOM = 4
TILE_MAX_ZOOM = 14

# Below this cosine similarity, the closest passage in the corpus is not about
# the question, and the honest answer is to say so rather than write around it.
#
# This was declared twice with two different values - 0.45 in the HTTP layer and
# 0.25 in the service - and only the 0.25 was ever read. Anyone reading the
# route to find out how strict the gate was got the wrong answer.
MIN_RELEVANCE = 0.25
