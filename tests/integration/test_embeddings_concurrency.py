"""Several questions at once must not crash the server.

The embedding model crashes the process when called from several threads at
the same time, which is what happens when a few people ask together.
"""

import concurrent.futures as cf

from api import embeddings


def test_many_requests_at_once_do_not_crash():
    texts = [f"escuelas en zona inundable cerca del río {i}" * (1 + i % 5) for i in range(200)]
    with cf.ThreadPoolExecutor(12) as pool:
        out = list(pool.map(embeddings.vector, texts))
    assert len(out) == 200
    assert all(v.startswith("[") for v in out)
