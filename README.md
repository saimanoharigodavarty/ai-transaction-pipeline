# AI-Powered Transaction Processing Pipeline

An asynchronous backend API to clean financial transaction data, flag statistical/rule-based anomalies, classify missing categories using Gemini 1.5 Flash, and generate spending narrative summaries.

Built using **FastAPI**, **PostgreSQL**, **Celery**, **Redis**, **Docker**, and **Gemini 1.5 Flash**.

---

## Architecture & Data Flow

1. **Upload**: User uploads a messy transactions CSV through `POST /jobs/upload`.
2. **Enqueue**: The API saves the file, inserts a `Job` (status = `pending`), queues the task in Redis, and immediately returns a `job_id`.
3. **Clean & Flag**: The Celery worker picks up the job, cleans the records (standardising dates, stripping currency signs, removing duplicates), and flags anomalies:
   * **Statistical Outliers**: Transactions > 3x the account's median transaction amount.
   * **Location/Currency Mismatch**: USD transaction with domestic brands (e.g. Swiggy, Ola, IRCTC).
4. **LLM Enrichment**: The worker batches uncategorized transactions to classify them via Gemini 1.5 Flash, then requests a spending narrative summary and risk level.
5. **Persist**: The worker saves all records to PostgreSQL and marks the job as `completed` (or `failed` if an unrecoverable error occurs).
6. **Retrieve**: The user checks progress via `GET /jobs/{id}/status` and retrieves structured results via `GET /jobs/{id}/results`.

---

## Technical Stack

* **API**: FastAPI (Uvicorn)
* **Database**: PostgreSQL (SQLAlchemy ORM)
* **Task Queue**: Celery (using Redis as the message broker)
* **LLM**: Gemini 1.5 Flash (`google-generativeai` SDK)
* **Infrastructure**: Docker & Docker Compose

---

## Setup & Running

### 1. Prerequisites
* [Docker and Docker Compose](https://docs.docker.com/get-docker/) installed.

### 2. Configuration
Create a `.env` file in the root directory (based on `.env.example`):
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Spin Up Services
Run the following command to build and start the entire stack:
```bash
docker compose up --build
```
This starts:
* **PostgreSQL** on port `5432`
* **Redis** on port `6379`
* **FastAPI API** on port `8000` (documentation available at http://localhost:8000/docs)
* **Celery Worker** (runs background jobs)

---

## API Endpoints & Example Requests

### 1. Upload CSV
Upload a transaction CSV file.
* **Endpoint**: `POST /jobs/upload`
* **Request**:
```bash
curl -X POST "http://localhost:8000/jobs/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@transactions.csv"
```
* **Response**:
```json
{
  "job_id": 1,
  "status": "pending"
}
```

### 2. Get Job Status
Check the processing status of a job.
* **Endpoint**: `GET /jobs/{job_id}/status`
* **Request**:
```bash
curl -X GET "http://localhost:8000/jobs/1/status"
```
* **Response**:
```json
{
  "job_id": 1,
  "status": "completed",
  "row_count_raw": 90,
  "row_count_clean": 85,
  "created_at": "2026-07-02T14:40:00.000000",
  "completed_at": "2026-07-02T14:40:05.000000"
}
```

### 3. Get Job Results
Retrieve the fully cleaned records, flagged anomalies, and Gemini-generated summaries.
* **Endpoint**: `GET /jobs/{job_id}/results`
* **Request**:
```bash
curl -X GET "http://localhost:8000/jobs/1/results"
```
* **Response**:
```json
{
  "status": "completed",
  "transactions": [
    {
      "txn_id": "TXN001",
      "merchant": "Swiggy",
      "amount": 450.0,
      "currency": "INR",
      "category": "Food",
      "is_anomaly": false,
      "anomaly_reason": null
    },
    {
      "txn_id": "TXN002",
      "merchant": "Ola Cabs",
      "amount": 1200.0,
      "currency": "USD",
      "category": "Transport",
      "is_anomaly": true,
      "anomaly_reason": "USD transaction with domestic brand Ola Cabs"
    }
  ],
  "summary": {
    "total_spend_inr": 450.0,
    "total_spend_usd": 1200.0,
    "top_merchants": ["Ola Cabs", "Swiggy"],
    "anomaly_count": 1,
    "narrative": "The user spent mainly on food and transport. A suspicious USD transaction was flagged on Ola Cabs.",
    "risk_level": "medium"
  }
}
```

### 4. List All Jobs
List all uploaded jobs with optional state filtering.
* **Endpoint**: `GET /jobs`
* **Request**:
```bash
curl -X GET "http://localhost:8000/jobs?status=completed"
```
* **Response**:
```json
[
  {
    "id": 1,
    "filename": "transactions.csv",
    "status": "completed",
    "row_count": 85,
    "created_at": "2026-07-02T14:40:00.000000"
  }
]
```
