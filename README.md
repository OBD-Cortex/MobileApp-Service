# Hybrid Automotive RAG: AI Mechanic Assistant

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green) ![Architecture](https://img.shields.io/badge/Architecture-Hybrid%20RAG-purple)

## [*] Project Overview
This repository hosts a **Hybrid Retrieval-Augmented Generation (RAG)** system designed for automotive diagnostics. It bridges the gap between raw vehicle telemetry and technical repair documentation.

The system operates on a **"Two-Stream" Architecture**:
1.  **Stream A (Knowledge):** Semantic search over PDF Repair Manuals & DTC Databases (Static Knowledge).
2.  **Stream B (Context):** Real-time ingestion of CAN Bus telemetry data (Dynamic Context).

It is lightweight enough to run on edge devices (like a Raspberry Pi 4) while offloading cognitive processing to a cloud LLM.

---

## [*] System Architecture

The core innovation is the dual-retrieval pipeline which prevents the AI from "hallucinating" vehicle status.

```text
[ VEHICLE / SIMULATOR ] 
      │
      ▼
(Stream B: Live Telemetry) ──▶ [ MongoDB Time-Series Collection ] ──┐
                                                                    │
                                                                    ▼
[ REPAIR MANUALS (PDF) ] ────▶ [ MongoDB Vector Store ] ────────▶ [ HYBRID RAG ENGINE ] ──▶ [ Google Gemini API ]
      ▲                                                             │
      │                                                             ▼
(Stream A: Static Knowledge)                                [ USER INTERFACE ]
```

## [*] Testing

All test scripts are located in the `Testing/` directory. These tests are meant to run locally and are ignored by version control.
Please ensure you use the project's dedicated virtual environment `obd-venv` when running tests.

```bash
source obd-venv/bin/activate
python Testing/test_retrieve.py
```

---

## [*] Architectural & Modular Enhancements

To align with high production standards and modular robustness according to `AGENTS.md`, several core improvements were implemented:
1. **Case-Insensitive Device Token Verification**: Normalized device tokens to uppercase across verification, mobile signup, and admin routes to prevent registration/unpairing mismatches.
2. **Environment Injection (Security)**: Removed local `python-dotenv` reading to strictly adhere to security constraints. All environment variables are natively injected by the OS or Docker host.
3. **Database Date Parsing**: The telemetry edge gateway API parses incoming ISO-8601 string timestamps into native Python datetime objects before insertion, guaranteeing BSON Date integrity in MongoDB.
4. **LLM Engine Refactoring**: Abstracted over 150 lines of duplicate API retry, rate-limiting, and Google Gemini execution logic into a clean, single-function functional pipeline.
5. **Chat History Protection (API Error Safety Guard)**: Added checks in mobile and legacy chat endpoints to detect LLM API failures (prefixed with `Diagnostic Engine Error:`) and raise a `502 Bad Gateway` HTTP error rather than persisting them in the chat history.
6. **Unique Device Provisioning**: Implemented a retry verification loop for candidate edge device IDs in the registration pathway to ensure device ID collisions do not occur in production.
7. **Database Index Verification**: Added programmatic setup of unique indexes for `device_token` and `device_id` on the devices collection, preventing duplication at the BSON layer.
8. **Bulk Ingestor File Type Alignment**: Added native processing of `.md` and `.txt` files to the bulk vectorization worker (`ingestor.py`) to align with the RAG manual ingestion API capabilities.
9. **Account Deletion Database Integrity**: Upgraded the account deletion flow to read bindings directly from the MongoDB user document rather than trust incoming JWT claims, ensuring clean device unpairing and data scrubbing.

