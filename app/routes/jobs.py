from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import os
from datetime import datetime
from app.database import get_db
from app.models.models import Job, Transaction, JobSummary
from app.workers.tasks import process_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])

@router.post("/upload")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accepts a CSV file upload. Validates it, creates a Job record in the database
    with status=pending, enqueues the processing task to Celery, and returns the job_id immediately.
    """
    # Validate file extension
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")
        
    # Ensure uploads directory exists
    os.makedirs("uploads", exist_ok=True)
    
    # Save file locally
    filepath = f"uploads/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    try:
        with open(filepath, "wb") as f:
            f.write(await file.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Create Job record in PostgreSQL
    job = Job(
        filename=file.filename,
        status="pending",
        row_count_raw=0,
        row_count_clean=0
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Enqueue background worker task via Celery
    process_job.delay(job.id, filepath)
    
    return {
        "job_id": job.id,
        "status": job.status
    }

@router.get("/{job_id}/status")
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    """
    Returns the current status of the job (pending, processing, completed, or failed).
    If completed, also includes high-level statistics.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    response = {
        "job_id": job.id,
        "status": job.status,
        "filename": job.filename,
        "row_count_raw": job.row_count_raw,
        "row_count_clean": job.row_count_clean,
        "created_at": job.created_at,
        "completed_at": job.completed_at
    }
    
    # Include high-level stats if completed
    if job.status == "completed":
        summary = db.query(JobSummary).filter(JobSummary.job_id == job_id).first()
        response["summary"] = {
            "total_spend_inr": summary.total_spend_inr if summary else 0.0,
            "total_spend_usd": summary.total_spend_usd if summary else 0.0,
            "top_merchants": summary.top_merchants if summary else [],
            "anomaly_count": summary.anomaly_count if summary else 0
        }
        
    return response

@router.get("/{job_id}/results")
def get_job_results(job_id: int, db: Session = Depends(get_db)):
    """
    Returns the full structured output:
    - Cleaned transactions list
    - Flagged anomalies
    - Per-category spend breakdown
    - LLM-generated narrative summary and risk level
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status != "completed":
        return {
            "status": job.status,
            "message": "Results are only available once the job is completed."
        }
        
    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    summary = db.query(JobSummary).filter(JobSummary.job_id == job_id).first()
    
    # 1. Cleaned transactions list
    cleaned_txns = []
    # 2. Flagged anomalies
    anomalies = []
    # 3. Per-category spend breakdown (calculated dynamically)
    category_breakdown = {}
    
    for t in transactions:
        txn_data = {
            "txn_id": t.txn_id,
            "date": t.date,
            "merchant": t.merchant,
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "category": t.category,
            "account_id": t.account_id,
            "notes": t.notes,
            "is_anomaly": t.is_anomaly,
            "anomaly_reason": t.anomaly_reason
        }
        cleaned_txns.append(txn_data)
        
        # Add to anomalies if flagged
        if t.is_anomaly:
            anomalies.append({
                "txn_id": t.txn_id,
                "merchant": t.merchant,
                "amount": t.amount,
                "currency": t.currency,
                "reason": t.anomaly_reason
            })
            
        # Add to per-category spend breakdown
        cat = t.category or "Uncategorised"
        if cat not in category_breakdown:
            category_breakdown[cat] = {}
        if t.currency not in category_breakdown[cat]:
            category_breakdown[cat][t.currency] = 0.0
        category_breakdown[cat][t.currency] += t.amount

    return {
        "status": job.status,
        "transactions": cleaned_txns,
        "anomalies": anomalies,
        "category_breakdown": category_breakdown,
        "summary": {
            "total_spend_inr": summary.total_spend_inr if summary else 0.0,
            "total_spend_usd": summary.total_spend_usd if summary else 0.0,
            "top_merchants": summary.top_merchants if summary else [],
            "anomaly_count": summary.anomaly_count if summary else 0,
            "narrative": summary.narrative if summary else "",
            "risk_level": summary.risk_level if summary else "unknown"
        } if summary else None
    }

@router.get("")
def list_jobs(status: str = Query(None, description="Filter jobs by status"), db: Session = Depends(get_db)):
    """
    List all jobs with their status, filename, row count, and created_at timestamp.
    Supports filtering via ?status= query parameter.
    """
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
        
    jobs = query.order_by(Job.created_at.desc()).all()
    return [
        {
            "id": j.id,
            "filename": j.filename,
            "status": j.status,
            "row_count": j.row_count_clean,
            "created_at": j.created_at
        } for j in jobs
    ]
