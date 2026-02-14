import os
import pdfplumber
import logging
import weaviate
from sentence_transformers import SentenceTransformer
from typing import List
import uuid

# Setup simple logging without timestamps (for clarity)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)
logger = logging.getLogger(__name__)

# Initialize embedding model and Weaviate client (v4 syntax)
model = SentenceTransformer("all-MiniLM-L6-v2")
weaviate_client = weaviate.connect_to_local(
    host="localhost",
    port=8081,
    grpc_port=50051
)

def create_schema():
    """Create Weaviate schema for astrology passages"""
    try:
        # Check if collection already exists
        if weaviate_client.collections.exists("AstroPassage"):
            logger.info("ℹ️ AstroPassage collection already exists")
            return
        
        # Create collection with schema
        weaviate_client.collections.create(
            name="AstroPassage",
            description="Astrological text passages from Vedic books",
            properties=[
                weaviate.classes.config.Property(
                    name="content",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="The text content of the passage"
                ),
                weaviate.classes.config.Property(
                    name="source",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Source PDF filename"
                ),
                weaviate.classes.config.Property(
                    name="chunkIndex",
                    data_type=weaviate.classes.config.DataType.INT,
                    description="Index of the chunk within the document"
                ),
                weaviate.classes.config.Property(
                    name="chapterTitle",
                    data_type=weaviate.classes.config.DataType.TEXT,
                    description="Chapter or section title"
                )
            ],
            # No vectorizer - we'll provide our own vectors
            vectorizer_config=None
        )
        
        logger.info("✅ Created AstroPassage collection in Weaviate")
        
    except Exception as e:
        logger.error(f"❌ Error creating schema: {e}")
        raise

def extract_text(pdf_path: str) -> str:
    """Extract text from PDF"""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        logger.info(f"Ingesting '{pdf_path}': total pages = {total_pages}")
        for i, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            text += page_text + "\n"
            if i % 10 == 0 or i == total_pages:
                logger.info(f"  Extracted page {i}/{total_pages}")
    return text

def chunk_text(text: str, max_words: int = 400) -> List[str]:
    """Split text into chunks"""
    words = text.split()
    chunks = [" ".join(words[i:i+max_words]) for i in range(0, len(words), max_words)]
    logger.info(f"Text split into {len(chunks)} chunks (max {max_words} words each)")
    return chunks

def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for text chunks"""
    logger.info(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True)
    return embeddings.tolist()

def ingest(pdf_path: str):
    """Ingest PDF into Weaviate"""
    logger.info(f"→ Starting ingestion for {pdf_path}")
    
    # Create schema first
    create_schema()
    
    # Get the collection
    collection = weaviate_client.collections.get("AstroPassage")
    
    # Extract text
    text = extract_text(pdf_path)
    if len(text) < 100:
        logger.warning(f"⚠️ Not enough text to ingest in {pdf_path}")
        return
    
    # Chunk text
    chunks = chunk_text(text)
    source = os.path.basename(pdf_path)
    
    # Process in batches to avoid memory issues
    batch_size = 50
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    
    for batch_num, i in enumerate(range(0, len(chunks), batch_size), start=1):
        batch_chunks = chunks[i:i + batch_size]
        
        # Filter out very short chunks
        valid_chunks = []
        valid_indices = []
        
        for idx, chunk in enumerate(batch_chunks):
            if len(chunk.strip()) >= 20:  # Minimum 20 characters
                valid_chunks.append(chunk.strip())
                valid_indices.append(i + idx)
        
        if not valid_chunks:
            logger.info(f"{source}: Batch {batch_num}/{total_batches} - no valid chunks")
            continue
        
        # Generate embeddings for this batch
        batch_embeddings = generate_embeddings(valid_chunks)
        
        # Prepare objects for Weaviate v4
        objects_to_add = []
        for chunk, chunk_idx, embedding in zip(valid_chunks, valid_indices, batch_embeddings):
            obj = weaviate.classes.data.DataObject(
                properties={
                    "content": chunk,
                    "source": source,
                    "chunkIndex": chunk_idx,
                    "chapterTitle": "Unknown"
                },
                vector=embedding,
                uuid=uuid.uuid4()
            )
            objects_to_add.append(obj)
        
        # Add to Weaviate using batch insert
        try:
            response = collection.data.insert_many(objects_to_add)
            
            if response.has_errors:
                logger.error(f"❌ Batch {batch_num} had errors:")
                for i, error in enumerate(response.errors):
                    if error:
                        logger.error(f"  Object {i}: {error}")
            else:
                logger.info(f"{source}: Processed batch {batch_num}/{total_batches} ({len(valid_chunks)} chunks added)")
            
        except Exception as e:
            logger.error(f"❌ Error adding batch {batch_num}: {e}")
            continue
    
    logger.info(f"← Completed ingestion for {pdf_path}")
    
    # Verify ingestion
    try:
        total_count = collection.aggregate.over_all(total_count=True).total_count
        logger.info(f"📊 Total passages in Weaviate: {total_count}")
    except Exception as e:
        logger.warning(f"⚠️ Could not get count: {e}")

def test_query(query_text: str = "planetary positions"):
    """Test querying the ingested data"""
    logger.info(f"🔍 Testing query: '{query_text}'")
    
    try:
        # Get collection
        collection = weaviate_client.collections.get("AstroPassage")
        
        # Generate embedding for query
        query_embedding = model.encode([query_text])[0].tolist()
        
        # Perform vector search
        response = collection.query.near_vector(
            near_vector=query_embedding,
            limit=3,
            return_properties=["content", "source", "chunkIndex"]
        )
        
        if response.objects:
            logger.info(f"✅ Found {len(response.objects)} relevant passages:")
            for i, obj in enumerate(response.objects, 1):
                content_preview = obj.properties['content'][:100] + "..." if len(obj.properties['content']) > 100 else obj.properties['content']
                logger.info(f"  {i}. {obj.properties['source']} (chunk {obj.properties['chunkIndex']}): {content_preview}")
        else:
            logger.info("❌ No passages found")
            
    except Exception as e:
        logger.error(f"❌ Query test failed: {e}")

if __name__ == "__main__":
    # Check if Weaviate is running
    try:
        if weaviate_client.is_ready():
            logger.info(f"✅ Connected to Weaviate")
        else:
            logger.error("❌ Weaviate is not ready")
            exit(1)
    except Exception as e:
        logger.error(f"❌ Cannot connect to Weaviate: {e}")
        logger.error("Make sure Weaviate is running: docker compose up -d")
        exit(1)
    
    try:
        # Ingest PDF
        pdf_file = "vedicbook9.pdf"
        if not os.path.exists(pdf_file):
            logger.error(f"PDF '{pdf_file}' not found. Please place the file in the current folder.")
        else:
            ingest(pdf_file)
            
            # Test the ingestion with a sample query
            test_query("planetary positions and astrological houses")
    
    finally:
        # Close connection
        weaviate_client.close()
