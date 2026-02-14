import chromadb
import logging
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.config import settings


logger = logging.getLogger(__name__)


try:
    from app.config.settings import settings
    model_name = getattr(settings, 'EMBEDDING_MODEL_NAME', 'all-MiniLM-L6-v2')
except (ImportError, AttributeError) as e:
    print(f"Settings import error: {e}")
    model_name = 'all-MiniLM-L6-v2'  # Fallback


def create_chroma_client():
    embeddings = HuggingFaceEmbeddings(model_name=model_name)
    
    if settings.USE_CHROMA_CLOUD and all([
        settings.CHROMA_API_KEY, 
        settings.CHROMA_TENANT, 
        settings.CHROMA_DATABASE
    ]):
        try:
            logger.info("Attempting to connect to ChromaDB Cloud...")
            chroma_client = chromadb.CloudClient(
                api_key=settings.CHROMA_API_KEY,
                tenant=settings.CHROMA_TENANT,
                database=settings.CHROMA_DATABASE
            )
            
            collections = chroma_client.list_collections()
            logger.info(f"✅ ChromaDB Cloud connected. Collections: {[c.name for c in collections]}")
            
            collection_name = settings.CHROMA_DATABASE  
            
            vector_store = Chroma(
                client=chroma_client,
                collection_name=collection_name,
                embedding_function=embeddings
            )
            
            return chroma_client, vector_store
            
        except Exception as e:
            logger.error(f"❌ ChromaDB Cloud connection failed: {e}")
            logger.info("Falling back to local ChromaDB...")
    
    # Fallback to local ChromaDB
    logger.info("Using local ChromaDB...")
    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_LOCAL_PATH)
    
    vector_store = Chroma(
        client=chroma_client,
        collection_name=settings.CHROMA_COLLECTION_NAME,
        embedding_function=embeddings
    )
    
    logger.info("✅ Local ChromaDB connected")
    return chroma_client, vector_store

def test_chroma_connection(vector_store):
    try:
        docs = vector_store.similarity_search("sun sign", k=1)
        logger.info(f"✅ ChromaDB test successful. Found {len(docs)} documents")
        return True
    except Exception as e:
        logger.error(f"❌ ChromaDB test failed: {e}")
        return False

chroma_client, vector_store = create_chroma_client()

def get_relevant_passages(query: str, k: int = 8) -> str:
    try:
        docs = vector_store.similarity_search(query, k=k)
        if not docs:
            return "Classical Vedic astrological wisdom applies."
        
        texts = [d.page_content for d in docs]
        joined = "\n\n---\n\n".join(texts)
        logger.info(f"Retrieved {len(docs)} passages from cloud, total length: {len(joined)} characters")
        return joined[:2000] + ("..." if len(joined) > 2000 else "")
    except Exception as e:
        logger.error(f"Error retrieving from cloud knowledge base: {e}")
        return "Error retrieving from knowledge base. Using classical principles."
    
def safe_get_relevant_passages(query, k=6):
    """Wrapper around get_relevant_passages to handle tuple return values"""
    try:
        passages = get_relevant_passages(query, k)
        if isinstance(passages, tuple):
            return list(passages)
        return passages
    except Exception as e:
        logger.error(f"Error in safe_get_relevant_passages: {e}")
        return []