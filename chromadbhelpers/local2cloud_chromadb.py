import chromadb
import argparse

# Initialize clients
cloud = chromadb.CloudClient(
    api_key='ck-5RVg49VgrEWAFcPDnS82MQL5uTJuB2y4TtmrKCqLuFGC',
    tenant='cf82d192-9824-4596-a741-a874e27c7d35',
    database='qa_astroapp'
)
local = chromadb.PersistentClient(path="./chromadb_data")

def sync_source_to_cloud(source_name: str):
    # Get collections
    local_col = local.get_collection("astro_passages")
    cloud_col = cloud.get_collection("qa_astroapp")
    
    # Get source data from local
    local_data = local_col.get(
        where={"source": source_name},
        include=["embeddings", "metadatas", "documents"]
    )
    
    if not local_data["ids"]:
        print(f"No data found for source: {source_name}")
        return
    
    # Delete existing cloud data for this source
    cloud_col.delete(where={"source": source_name})
    
    # Upload new data in batches
    batch_size = 300
    for i in range(0, len(local_data["ids"]), batch_size):
        batch = {
            "ids": local_data["ids"][i:i+batch_size],
            "embeddings": local_data["embeddings"][i:i+batch_size],
            "metadatas": local_data["metadatas"][i:i+batch_size],
            "documents": local_data["documents"][i:i+batch_size]
        }
        cloud_col.upsert(**batch)
        print(f"Uploaded batch {i//batch_size + 1} | Items: {len(batch['ids'])}")
    
    print(f"✅ Successfully synced '{source_name}' to cloud")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="PDF filename to sync (e.g. 'vedicbook20.pdf')")
    args = parser.parse_args()
    sync_source_to_cloud(args.source)