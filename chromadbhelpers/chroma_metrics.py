import chromadb
from langchain.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

def check_chroma_metrics(persist_dir="./chromadb_data", collection_name="astro_passages"):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    client = chromadb.PersistentClient(path=persist_dir)
    
    chroma_store = Chroma(client=client, collection_name=collection_name, embedding_function=embeddings)
    collection = chroma_store._collection  
    
    # Get document count
    doc_count = collection.count()
    print(f"Total documents in '{collection_name}': {doc_count}")

    # Get collection stats
    try:
        stats = collection.get(include=["metadatas", "documents"], limit=5)
        print(f"Sample documents and metadata (up to 5):")
        for i, (doc, meta) in enumerate(zip(stats["documents"], stats["metadatas"]), start=1):
            print(f"Doc #{i}: '{doc[:60]}...'")
            print(f"Metadata: {meta}")
    except Exception as e:
        print(f"Could not fetch sample documents: {e}")


if __name__ == "__main__":
    check_chroma_metrics()
