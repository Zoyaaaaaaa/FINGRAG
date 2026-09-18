"""PDF ingestion script for FinGraphRAG - extracts text from PDF and inserts into Qdrant."""

import hashlib
import re
from pathlib import Path
from typing import Any

from src.config.settings import get_settings
from src.tools.qdrant_tools import QdrantStore


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF file."""
    try:
        # Try PyPDF2 first (most common)
        try:
            import PyPDF2
            with pdf_path.open("rb") as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except ImportError:
            pass
        
        # Fallback to pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                for page in pdf.pages:
                    text += page.extract_text() + "\n"
                return text
        except ImportError:
            pass
        
        # Fallback to pypdf
        try:
            import pypdf
            with pdf_path.open("rb") as file:
                reader = pypdf.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except ImportError:
            pass
        
        raise ImportError("No PDF library found. Install one of: PyPDF2, pdfplumber, or pypdf")
    
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {e}")


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks for better retrieval."""
    # Clean up the text first
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = text.strip()
    
    if not text:
        return []
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        
        # Try to break at a sentence boundary
        if end < text_length:
            # Look for sentence endings near the chunk boundary
            sentence_endings = ('. ', '! ', '? ', '\n')
            best_break = end
            
            for ending in sentence_endings:
                # Look for the ending before the chunk end
                break_pos = text.rfind(ending, start, end)
                if break_pos > start:
                    best_break = break_pos + len(ending)
                    break
            
            end = best_break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap  # Overlap chunks for context
        
        # Avoid infinite loop
        if start >= end:
            break
    
    return chunks


def ingest_pdf(
    pdf_path: str,
    settings: Any = None,
    qdrant: QdrantStore | None = None,
    chunk_size: int = 1000,
    overlap: int = 200
) -> dict[str, Any]:
    """Ingest a PDF file into Qdrant vector database.
    
    Args:
        pdf_path: Path to the PDF file
        settings: Application settings (optional)
        qdrant: QdrantStore instance (optional)
        chunk_size: Size of text chunks in characters
        overlap: Overlap between chunks in characters
    
    Returns:
        Dictionary with ingestion statistics
    """
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_file}")
    
    if settings is None:
        settings = get_settings()
    
    if qdrant is None:
        qdrant = QdrantStore(settings)
    
    print(f"Extracting text from PDF: {pdf_file.name}")
    text = extract_text_from_pdf(pdf_file)
    
    if not text.strip():
        raise ValueError("No text could be extracted from the PDF")
    
    print(f"Extracted {len(text)} characters from PDF")
    
    # Chunk the text
    print(f"Chunking text (chunk_size={chunk_size}, overlap={overlap})")
    chunks = chunk_text(text, chunk_size, overlap)
    print(f"Created {len(chunks)} chunks")
    
    # Prepare documents for Qdrant
    documents = []
    for index, chunk in enumerate(chunks):
        # Create deterministic ID for this chunk
        chunk_id = hashlib.sha256(
            f"{pdf_file.name}_{index}_{chunk[:100]}".encode()
        ).hexdigest()[:32]
        
        doc = {
            "text": chunk,
            "metadata": {
                "source": pdf_file.name,
                "chunk_index": index,
                "total_chunks": len(chunks),
                "chunk_size": len(chunk),
                "file_type": "pdf"
            }
        }
        documents.append(doc)
    
    # Upsert to Qdrant
    print(f"Upserting {len(documents)} chunks to Qdrant")
    count = qdrant.upsert(documents)
    
    result = {
        "file": pdf_file.name,
        "total_characters": len(text),
        "chunks_created": len(chunks),
        "qdrant_points_upserted": count,
        "chunk_size": chunk_size,
        "overlap": overlap
    }
    
    print(f"Ingestion complete: {result}")
    return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest PDF file into Qdrant")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--chunk-size", type=int, default=1000, help="Chunk size in characters")
    parser.add_argument("--overlap", type=int, default=200, help="Overlap between chunks in characters")
    
    args = parser.parse_args()
    
    try:
        result = ingest_pdf(
            args.pdf_path,
            chunk_size=args.chunk_size,
            overlap=args.overlap
        )
        print("\n[SUCCESS] PDF ingestion successful!")
        print(f"Results: {result}")
    except Exception as e:
        print(f"\n[FAIL] PDF ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())