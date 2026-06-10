# OBD-Cortex: MobileApp Service

The **MobileApp Service** is the heavy-lifting AI backend of the OBD-Cortex platform. It powers the end-user conversational interfaces, providing highly nuanced diagnostic guidance via Retrieval-Augmented Generation (RAG) powered by local text embeddings.

## Architecture Overview

1. **Local NLP Embeddings**: Utilizes the `microsoft/harrier-oss-v1-270m` SentenceTransformer model (loaded in `src/core/models.py`) to generate semantic embeddings at zero-token-cost directly on the host CPU.
2. **Asynchronous Ingestion Pipeline**: Exposes endpoints for the Admin Dashboard to upload massive, 500+ page technical manuals and CSV catalogs. These are chunked and ingested asynchronously using `src/workers/ingestor.py` so as not to block incoming RAG queries.
3. **Database Architecture**: Connects to the centralized MongoDB Atlas cluster (`src/core/database.py`). It relies heavily on Atlas Vector Search to retrieve contextually relevant vehicle repair data to feed into the conversational logic.

## Repository Structure

- `src/core/`: Database initialization, configuration logic, and the local `SentenceTransformer` instantiation.
- `src/routes/`: Client-facing endpoints for mobile app chat and authentication, plus admin ingestion webhooks.
- `src/workers/`: Background asynchronous tasks for heavy document parsing and Pandas DataFrame manipulations.
- `src/main_api.py`: The root Uvicorn entrypoint for the service.
- `systemd/`: Contains the daemon deployment configurations for Linux hosts.

## Local Development (Quick Start)

To run the RAG and Chat backend locally:
1. Ensure **Python 3.10+** is installed.
2. Create and activate a virtual environment: `python -m venv venv && source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy the environment variables: `cp .env.example .env` and fill in the required values.
5. Start the development server: `uvicorn src.main_api:app --reload`

*(Note: The first time you boot the server, it will download the 1GB `microsoft/harrier-oss-v1-270m` SentenceTransformer model locally. This may take a few minutes depending on your connection.)*

## Deployment

Please refer to `DEPLOYMENT.md` for a comprehensive, production-grade deployment guide on DigitalOcean using Nginx, Certbot, and Fish. Due to the Pandas and embedding operations, **Swap memory configuration is critical** for this service.
