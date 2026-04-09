import os
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from app.utils import load_data

COLLECTION_NAME = "limbu_kb"


def get_client():
    return QdrantClient(
        url=os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )


def get_embeddings():
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.getenv("OPENAI_API_KEY")
    )


def create_collection():
    client = get_client()
    collections = client.get_collections().collections
    names = [c.name for c in collections]

    if COLLECTION_NAME not in names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        return True  # Naya bana
    return False  # Pehle se hai


def get_qdrant():
    # langchain-qdrant 1.1.0 mein QdrantVectorStore use hota hai
    return QdrantVectorStore(
        client=get_client(),
        collection_name=COLLECTION_NAME,
        embedding=get_embeddings()
    )


def insert_data():
    is_new = create_collection()

    if not is_new:
        client = get_client()
        count = client.count(collection_name=COLLECTION_NAME)
        if count.count > 0:
            print(f"✅ Qdrant already has {count.count} records. Skipping insert.")
            return

    qdrant = get_qdrant()
    data = load_data()
    texts = [d["text"] for d in data]
    metadata = [{"type": d["type"], "id": d["id"]} for d in data]

    qdrant.add_texts(texts=texts, metadatas=metadata)
    print(f"✅ {len(texts)} records inserted into Qdrant.")


def search(query: str, k: int = 4) -> list:
    qdrant = get_qdrant()
    return qdrant.similarity_search(query, k=k)