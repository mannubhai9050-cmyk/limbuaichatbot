from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from app.core.config import (
    QDRANT_URL, QDRANT_API_KEY, OPENAI_API_KEY,
    QDRANT_COLLECTION, EMBEDDING_MODEL
)
from app.utils import load_data


def get_client() -> QdrantClient:
    return QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=30  # 30 second timeout
    )


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=OPENAI_API_KEY)


def get_qdrant() -> QdrantVectorStore:
    return QdrantVectorStore(
        client=get_client(),
        collection_name=QDRANT_COLLECTION,
        embedding=get_embeddings()
    )


def insert_data():
    """Insert knowledge base — skip if already exists"""
    try:
        client = get_client()
        collections = [c.name for c in client.get_collections().collections]

        if QDRANT_COLLECTION not in collections:
            client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )

        count = client.count(collection_name=QDRANT_COLLECTION).count
        expected = len(load_data())

        if count == expected:
            print(f"✅ Qdrant already has {count} records. Skipping insert.")
            return

        if count > 0:
            client.delete_collection(QDRANT_COLLECTION)
            client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )

        data = load_data()
        qdrant = get_qdrant()
        qdrant.add_texts(
            texts=[d["text"] for d in data],
            metadatas=[{"type": d["type"], "id": d["id"]} for d in data]
        )
        print(f"✅ {len(data)} records inserted into Qdrant.")
    except Exception as e:
        print(f"⚠️ Qdrant insert error: {e}")


def search(query: str, k: int = 4) -> list:
    """Semantic search — returns empty list on timeout/error"""
    try:
        return get_qdrant().similarity_search(query, k=k)
    except Exception as e:
        print(f"⚠️ Qdrant search error: {e}")
        return []  # Graceful fallback — Claude will still respond without KB context