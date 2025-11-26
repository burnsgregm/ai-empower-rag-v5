# AI Empower Enterprise RAG Service (V5)

This repository contains the source code and Infrastructure as Code (IaC) for the Version 5.0 deployment of the AI Empower Retrieval-Augmented Generation (RAG) Service.

V5 is a critical step in the scaling roadmap, implementing Storage Decoupling (Dual-Write) to mitigate future Firestore vector storage costs while preserving the real-time search performance of the production V4 system.

## Architecture Summary (V5: Storage Decoupling)

The V5 architecture maintains the core asynchronous Fan-Out pipeline but adds a secondary data export layer.

### Core Technology Stack

* IaC: Terraform
* Compute: Google Cloud Run (Containerized)
* Vector Search Engine: Firestore Native Vector Search (Live Query Layer)
* Archival Storage: GCS Parquet Files (V6 Source Data)
* Models: Gemini 2.5 Pro (Generation) and text-embedding-004 (Embedding)

### V5 Pipeline Flow

* GCS Upload: User uploads file to bucket (/uploads/{client_id}/).
* Dispatch/Queue: Eventarc triggers the Dispatcher, which queues pages to Pub/Sub.
* Worker (Dual Write): The Worker performs both:
* Real-time Indexing: Writes Child Vectors to Firestore (rag_children).
* Archival Export: Writes all chunk data (including vectors) to a compressed Parquet file in GCS (/archive/{client_id}/).
* Retrieval: The Retrieval API queries Firestore for the live search and uses Gemini for generation with conversational memory.
