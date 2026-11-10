import time

from app import store


def test_documents_and_collections():
    store.doc_set("plan_t/w1", {"days": {"mon": True}})
    store.doc_set("plan_t/w2", {"days": {}})
    store.doc_set("plan_t_other/x", {"n": 1})            # '_' must not act as a wildcard
    store.doc_set("plan_t/w1/notes/n1", {"deep": True})  # nested documents aren't part of the collection
    assert store.doc_get("plan_t/w1") == {"days": {"mon": True}}
    assert sorted(d["id"] for d in store.collection("plan_t")) == ["w1", "w2"]
    store.doc_merge("plan_t/w2", {"a": [True]})
    store.doc_merge("plan_t/w2", {"b": [False]})
    assert store.doc_get("plan_t/w2") == {"days": {}, "a": [True], "b": [False]}
    store.doc_delete("plan_t/w2")
    assert store.doc_get("plan_t/w2") is None


def test_cache_age_and_pruning():
    store.cache_put("strava:acts:2026-01-05", [1])
    store.cache_put("strava:acts_keep", [2])
    assert store.cache_get("strava:acts:2026-01-05", 60)[0] == [1]
    assert store.cache_get("strava:acts:2026-01-05", -1) is None
    with store._lock:
        store._db().execute("UPDATE kv SET stored = ?", (time.time() - 10 * 86400,))
        store._db().commit()
    store.cache_put("strava:acts:2026-11-09", [3])
    assert store.kv_prune("strava:acts:", 2 * 86400) == 1   # only the old weekly list goes
    assert store.kv_get("strava:acts_keep") == [2] and store.kv_get("strava:acts:2026-11-09") == [3]
