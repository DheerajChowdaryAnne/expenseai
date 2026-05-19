"""
services/rag_service.py — ChromaDB RAG Engine for Corporate Policy Search
=========================================================================
Manages a local persistent ChromaDB vector database that stores chunks of
uploaded corporate policy handbook PDFs. Provides semantic search so the
policy verifier can find relevant policy rules without exact keyword matches.

How RAG (Retrieval-Augmented Generation) works here:
  1. Admin uploads a policy PDF via POST /policy-documents
  2. ingest_pdf() extracts text, splits it into ~400-word overlapping chunks,
     and stores each chunk as a vector embedding in ChromaDB
  3. When verifying an expense, the policy verifier calls query() with a
     natural language question (e.g. "hotel nightly rate limit Chicago")
  4. ChromaDB finds the most semantically similar chunks using cosine
     similarity of the embedding vectors
  5. Top-k results (default k=4) are returned to Claude as tool_result content

Embedding model:
  Uses ChromaDB's default embedding function which wraps the
  sentence-transformers/all-MiniLM-L6-v2 model (384-dimensional vectors).
  This model is downloaded automatically on first use and cached locally.
  It is small (~80MB), fast, and works well for policy text similarity.

Chunking strategy:
  Word-based sliding window: 400 words per chunk with 80-word overlap.
  The overlap ensures that policy rules that span chunk boundaries are not
  lost. Chunks shorter than 20 characters are skipped (page headers, etc.).

Singleton pattern:
  get_rag_service() returns a module-level singleton. ChromaDB and the
  embedding model are loaded lazily on first use, then reused for all
  subsequent calls. On startup, main.py calls get_rag_service() to warm
  up the embedding model before the first user request arrives.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "enterprise_policy"  # ChromaDB collection name
CHUNK_SIZE = 400       # Target number of words per chunk
CHUNK_OVERLAP = 80     # Word overlap between adjacent chunks (prevents boundary loss)
MAX_RAG_RESULTS = 4    # Default top-k results per query


class RAGService:
    """
    Manages the ChromaDB collection for uploaded enterprise policy handbooks.

    All heavy initialisation (ChromaDB client + embedding model download) is
    deferred to the first actual use via _ensure_initialized(). This keeps
    import time fast and avoids loading the model if no policy docs exist.

    Public methods:
        ingest_pdf(file_path, doc_id, doc_name) → int  (number of chunks stored)
        delete_doc(doc_id) → int                       (number of chunks removed)
        query(query_text, n_results) → list[dict]      (semantic search results)
        has_documents() → bool                         (collection non-empty check)
    """

    def __init__(self) -> None:
        # Lazy-initialized — None until _ensure_initialized() is first called
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # Lazy Initialization
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """
        Initialize ChromaDB client and collection on first use.

        Creates the chroma_db directory if needed, connects to the
        persistent ChromaDB store, and gets (or creates) the collection
        with cosine similarity as the distance metric.

        Called automatically by all public methods — callers don't need
        to worry about initialization order.
        """
        if self._client is not None:
            return  # Already initialized — nothing to do

        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is required. Run: pip install chromadb>=0.4.22"
            ) from exc

        chroma_path = settings.chroma_dir
        Path(chroma_path).mkdir(parents=True, exist_ok=True)

        # PersistentClient stores embeddings on disk so they survive restarts
        self._client = chromadb.PersistentClient(path=chroma_path)

        # DefaultEmbeddingFunction wraps all-MiniLM-L6-v2 (384-dim vectors).
        # Downloaded automatically on first use and cached by sentence-transformers.
        ef = embedding_functions.DefaultEmbeddingFunction()

        # get_or_create_collection is idempotent — safe to call on every startup
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            # Use cosine similarity (range 0–1) instead of L2 Euclidean distance
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):
        """Return the ChromaDB collection, initializing if needed."""
        self._ensure_initialized()
        return self._collection

    # ------------------------------------------------------------------
    # Ingest (called in background task when a policy PDF is uploaded)
    # ------------------------------------------------------------------

    def ingest_pdf(self, file_path: str, doc_id: str, doc_name: str) -> int:
        """
        Extract text from a PDF, chunk it, embed it, and store in ChromaDB.

        This is a CPU-bound operation (PDF parsing + embedding computation).
        It is always called via asyncio.run_in_executor() from the async
        background task in main.py to avoid blocking the event loop.

        Args:
            file_path: Absolute path to the PDF file on disk.
            doc_id:    UUID for this document (used as ChromaDB metadata key).
            doc_name:  Human-readable document name (shown in policy notes).

        Returns:
            Number of chunks successfully stored in ChromaDB.
            Returns 0 if the PDF had no extractable text.
        """
        # Step 1: Extract all text from the PDF using pypdf
        text = self._extract_pdf_text(file_path)

        # Step 2: Split text into overlapping word-based chunks
        chunks = self._chunk_text(text, doc_id, doc_name)
        if not chunks:
            return 0  # Empty PDF or PDF with only images/no text

        # Step 3: Store all chunks in ChromaDB in a single batch operation.
        # ChromaDB automatically embeds each document text using the ef above.
        self.collection.add(
            documents=[c["text"] for c in chunks],     # Raw text chunks
            metadatas=[c["metadata"] for c in chunks], # doc_id, doc_name, chunk_index
            ids=[c["id"] for c in chunks],              # Unique chunk IDs
        )
        return len(chunks)

    def delete_doc(self, doc_id: str) -> int:
        """
        Remove all chunks for a given doc_id from ChromaDB.

        Called when a policy document is deleted via DELETE /policy-documents/{doc_id}.
        Uses ChromaDB's metadata filter to find all chunks belonging to this document.

        Args:
            doc_id: UUID of the document to delete.

        Returns:
            Number of chunks that were deleted.
        """
        self._ensure_initialized()
        # Query ChromaDB for all chunks with this doc_id in their metadata
        results = self.collection.get(where={"doc_id": doc_id})
        chunk_ids = results.get("ids", [])
        if chunk_ids:
            self.collection.delete(ids=chunk_ids)
        return len(chunk_ids)

    # ------------------------------------------------------------------
    # Query (called during expense policy verification)
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        n_results: int = MAX_RAG_RESULTS,
    ) -> list[dict]:
        """
        Semantic search over the enterprise policy corpus.

        Embeds the query text and finds the most similar chunks using cosine
        similarity. Returns results sorted by relevance (highest score first).

        Args:
            query_text: Natural language query (e.g. "hotel nightly rate limit").
            n_results:  Maximum number of chunks to return. Automatically clamped
                        to the collection size to prevent ChromaDB errors.

        Returns:
            List of dicts, each containing:
              - text:     The raw policy text chunk
              - doc_name: Human-readable document name
              - doc_id:   UUID of the source document
              - score:    Cosine similarity (0.0–1.0, higher = more relevant)
        """
        self._ensure_initialized()
        total = self.collection.count()
        if total == 0:
            return []  # No documents in the collection yet

        # ChromaDB raises an error if n_results > collection size, so clamp it
        clamped = min(n_results, total)

        results = self.collection.query(
            query_texts=[query_text],
            n_results=clamped,
            # Request all three data types we need for the response
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],   # Text content of each matching chunk
            results["metadatas"][0],   # Metadata dict for each chunk
            results["distances"][0],   # Cosine distance (lower = more similar)
        ):
            hits.append({
                "text":     doc,
                "doc_name": meta.get("doc_name", "Unknown"),
                "doc_id":   meta.get("doc_id", ""),
                # Convert cosine distance → similarity score (distance 0 = score 1.0)
                "score":    round(1.0 - float(dist), 4),
            })
        return hits

    def has_documents(self) -> bool:
        """
        Return True if the ChromaDB collection contains at least one chunk.

        Used as a guard in policy_verifier.py before adding rag_search to
        Claude's tool list — no point offering the tool if no docs exist.
        Returns False gracefully if ChromaDB fails to initialize.
        """
        try:
            self._ensure_initialized()
            return self.collection.count() > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pdf_text(file_path: str) -> str:
        """
        Extract all text from a PDF file using pypdf.

        pypdf is a pure-Python PDF parser that works without system
        dependencies. For scanned PDFs (image-only), extract_text()
        returns an empty string — those PDFs won't be indexed.

        Args:
            file_path: Absolute path to the PDF file.

        Returns:
            Full text content of the PDF as a single newline-joined string.

        Raises:
            RuntimeError: If pypdf is not installed.
        """
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                "pypdf is required. Run: pip install pypdf>=4.0.0"
            ) from exc

        reader = PdfReader(file_path)
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n".join(pages)

    @staticmethod
    def _chunk_text(text: str, doc_id: str, doc_name: str) -> list[dict]:
        """
        Split text into overlapping word-based chunks for ChromaDB storage.

        Chunking strategy:
          - Split on whitespace to get a word list
          - Sliding window: CHUNK_SIZE words, advance by (CHUNK_SIZE - CHUNK_OVERLAP)
          - This means each adjacent chunk shares CHUNK_OVERLAP words
          - Chunks shorter than 20 characters are skipped (typically page headers)

        The overlap ensures policy rules that span a chunk boundary appear in
        at least one complete chunk, improving retrieval accuracy.

        Args:
            text:     Full extracted text from the PDF.
            doc_id:   UUID of the document (stored in chunk metadata).
            doc_name: Human-readable name (stored in chunk metadata).

        Returns:
            List of chunk dicts, each with keys: id, text, metadata.
        """
        words = text.split()
        if not words:
            return []

        chunks: list[dict] = []
        chunk_index = 0
        start = 0

        while start < len(words):
            end = min(start + CHUNK_SIZE, len(words))
            chunk_text = " ".join(words[start:end]).strip()

            # Skip very short chunks — they're usually just page numbers or headers
            if len(chunk_text) > 20:
                chunks.append({
                    # Unique ID: doc_id + sequential chunk number
                    "id": f"{doc_id}_chunk_{chunk_index}",
                    "text": chunk_text,
                    "metadata": {
                        "doc_id":      doc_id,
                        "doc_name":    doc_name,
                        "chunk_index": chunk_index,
                    },
                })
                chunk_index += 1

            if end >= len(words):
                break  # Reached the end of the document

            # Slide window forward by (CHUNK_SIZE - CHUNK_OVERLAP) words
            start = end - CHUNK_OVERLAP

        return chunks


# ---------------------------------------------------------------------------
# Module-Level Singleton
# ---------------------------------------------------------------------------

_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """
    Return the shared RAGService instance (created on first call).

    Using a global singleton avoids re-loading ChromaDB and the embedding
    model on every request. The singleton is initialized lazily — ChromaDB
    and the model are only loaded when the first actual operation is performed.
    """
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
