import os
import pdfplumber
import logging
from sentence_transformers import SentenceTransformer
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import chromadb
from typing import List

# Setup simple logging without timestamps (for clarity)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)
logger = logging.getLogger(__name__)

# Initialize embedding model and Chroma client
model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./chromadb_data")

def extract_text(pdf_path: str) -> str:
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
    words = text.split()
    chunks = [" ".join(words[i:i+max_words]) for i in range(0, len(words), max_words)]
    logger.info(f"Text split into {len(chunks)} chunks (max {max_words} words each)")
    return chunks

def ingest(pdf_path: str):
    logger.info(f"→ Starting ingestion for {pdf_path}")

    text = extract_text(pdf_path)
    if len(text) < 100:
        logger.warning(f"⚠️ Not enough text to ingest in {pdf_path}")
        return

    chunks = chunk_text(text)
    source = os.path.basename(pdf_path)

    vector_store = Chroma(
        client=client,
        collection_name="astro_passages",
        embedding_function=embeddings
    )

    batch_size = 50
    total_batches = (len(chunks) + batch_size - 1) // batch_size

    for batch_num, i in enumerate(range(0, len(chunks), batch_size), start=1):
        batch_chunks = chunks[i:i + batch_size]
        texts, metadatas, ids = [], [], []

        for idx, chunk in enumerate(batch_chunks):
            if len(chunk.strip()) < 20:
                continue
            texts.append(chunk.strip())
            metadatas.append({
                "source": source,
                "chunkIndex": i + idx,
                "chapterTitle": "Unknown"
            })
            ids.append(f"{source}_{i + idx}")

        if texts:
            vector_store.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids
            )
        logger.info(f"{source}: Processed batch {batch_num}/{total_batches} ({len(texts)} chunks added)")

    logger.info(f"← Completed ingestion for {pdf_path}")
    text = extract_text(pdf_path)
    logger.info(f"Extracted text length: {len(text)} characters")
    if len(text.strip()) < 100:
        logger.warning(f"Text too short after extraction - skipping ingestion.")
        return


if __name__ == "__main__":
    pdf_file = "vedicbook23.pdf"
    if not os.path.exists(pdf_file):
        logger.error(f"PDF '{pdf_file}' not found. Please place the file in the current folder.")
    else:
        ingest(pdf_file)

