# OBD-Cortex: MobileApp Diagnostic Service

The **MobileApp Service** is the core AI-powered diagnostic engine of the OBD-Cortex platform. It powers conversational diagnostics via Retrieval-Augmented Generation (RAG) by merging live vehicle CAN bus data with context retrieved from technical manuals.

---

## Service Architecture

1.  **Local NLP Embeddings:** Generates semantic embeddings locally using the `microsoft/harrier-oss-v1-270m` SentenceTransformer model (instantiated in `src/core/models.py`). This runs entirely on the host CPU at zero token cost.
2.  **Asynchronous Ingestion Worker:** Exposes endpoints to ingest large manuals asynchronously. PDF manual processing runs in background threads (`src/workers/ingestor.py`) to prevent blocking API requests.
3.  **Advanced Vector Search:** Connects to MongoDB Atlas to execute similarity vector search matches (`get_manual_context` in `src/services/retrieval.py`). Only documents scoring above the similarity threshold (`0.55`) are fed to the model context.
4.  **AI Engine:** Integrates Google's Gemini Flash model (recommending `models/gemini-3.5-flash` in `src/services/llm_agent.py`) with fallback structures to handle API issues gracefully.
5.  **Multimodal Diagnostics:** Features base64-encoded image and audio diagnostic ingestion. It extracts symptoms from the media payload via Gemini before routing queries to standard RAG.
6.  **No Version Pins:** `requirements.txt` does not restrict package versions, ensuring you always pull the latest stable libraries during setup.

---

## Repository Structure

*   `src/core/models.py`: Initializes the local `SentenceTransformer` embedder.
*   `src/services/llm_agent.py`: Controls Gemini integration, content sanitization, retry blocks, and API key scrubbing.
*   `src/services/retrieval.py`: Vectors search calculations and live time-series telemetry context formatters.
*   `src/workers/ingestor.py`: Standard file scanner for bulk directory updates.
*   `src/main_api.py`: Uvicorn startup configs, LAN IP listeners, and rate-limiting registrations.

---

## Local Development Setup

To run this RAG and conversational engine locally:
1.  Verify **Python 3.10+** is installed.
2.  Initialize virtual environment:
    ```bash
    python -m venv venv && source venv/bin/activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Copy environment variables:
    ```bash
    cp .env.example .env
    ```
5.  Configure your MongoDB URI, API keys, and model overrides inside `.env`.
6.  Start development server:
    ```bash
    uvicorn src.main_api:app --reload
    ```

> [!NOTE]
> On the first startup, the daemon will download the 1GB `harrier-oss-v1-270m` transformer model. This can take a few minutes.

---


