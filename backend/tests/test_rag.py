from sqlmodel import create_engine

from intakeagent.db.engine import init_db
from intakeagent.db.models import ProtocolDoc
from intakeagent.db.rag import HashingEmbeddings, InMemoryStore, cosine
from intakeagent.db.seed_protocols import SEED, hint_for, seed_protocols


def test_hashing_embeddings_are_deterministic_and_normalised():
    emb = HashingEmbeddings()
    a, b = emb.embed(["medication dose frequency", "medication dose frequency"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6
    assert cosine(a, emb.embed(["allergy reaction latex"])[0]) < cosine(a, b)


def test_store_seed_and_search(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'rag.db').as_posix()}")
    init_db(engine)
    store = InMemoryStore(engine, HashingEmbeddings())
    assert seed_protocols(store) == len(SEED)
    assert seed_protocols(store) == 0  # idempotent
    hits = store.search("medication dose and how often", "healthcare", k=2)
    assert hits[0][0].field_name == "medications"
    assert hits[0][1] > 0


def test_hint_for_returns_protocol_text(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'rag2.db').as_posix()}")
    init_db(engine)
    store = InMemoryStore(engine, HashingEmbeddings())
    seed_protocols(store)
    assert "conflict" in (hint_for(store, "legal", "conflict_check_names") or "").lower()
    assert "allerg" in (hint_for(store, "healthcare", "allergies") or "").lower()


def test_store_add_custom_doc(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'rag3.db').as_posix()}")
    init_db(engine)
    store = InMemoryStore(engine, HashingEmbeddings())
    store.add(
        [ProtocolDoc(vertical="legal", field_name="urgency", title="x", content="court date")]
    )
    assert store.count("legal") == 1
    assert store.count("healthcare") == 0
