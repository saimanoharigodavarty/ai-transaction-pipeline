from celery import Celery
from datetime import datetime
import pandas as pd
from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
from app.database import SessionLocal
from app.models.models import Job, Transaction, JobSummary
from app.utils.cleaner import clean_transaction_data
from app.utils.anomaly import flag_anomalies
from app.utils.llm_service import classify_categories, generate_summary

# Initialize Celery app
celery_app = Celery(
    'tasks',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND
)

@celery_app.task(name="app.workers.tasks.process_job")
def process_job(job_id: int, csv_path: str):
    """
    Background worker task to orchestrate the entire transaction processing pipeline.
    """
    print(f"Starting processing for Job ID: {job_id} with file: {csv_path}")
    db = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        print(f"Error: Job ID {job_id} not found in database.")
        db.close()
        return

    try:
        # 1. Update Job status to processing
        job.status = "processing"
        db.commit()
        
        # 2. Read raw CSV
        df_raw = pd.read_csv(csv_path)
        job.row_count_raw = len(df_raw)
        db.commit()
        
        # 3. Clean transaction data
        df_clean = clean_transaction_data(df_raw)
        job.row_count_clean = len(df_clean)
        db.commit()
        
        # If no valid transactions remain after cleaning
        if df_clean.empty:
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            
            summary = JobSummary(
                job_id=job_id,
                total_spend_inr=0.0,
                total_spend_usd=0.0,
                top_merchants=[],
                anomaly_count=0,
                narrative="No transactions remained after the data cleaning phase.",
                risk_level="low"
            )
            db.add(summary)
            db.commit()
            db.close()
            return
            
        # 4. Detect anomalies (Rule-based & Statistical)
        # Initialize anomaly columns in dataframe
        df_clean['is_anomaly'] = False
        df_clean['anomaly_reason'] = None
        
        anomalies = flag_anomalies(df_clean)
        for anomaly in anomalies:
            idx = anomaly['index']
            df_clean.at[idx, 'is_anomaly'] = True
            df_clean.at[idx, 'anomaly_reason'] = anomaly['reason']

        # 5. Convert to dicts for in-memory LLM classification
        transactions_list = []
        for idx, row in df_clean.iterrows():
            transactions_list.append({
                'txn_id': row.get('txn_id'),
                'date': row['date'],
                'merchant': row['merchant'],
                'amount': float(row['amount']),
                'currency': row['currency'],
                'status': row['status'],
                'category': row['category'],
                'account_id': row['account_id'],
                'notes': row.get('notes') if pd.notna(row.get('notes')) else None,
                'is_anomaly': bool(row['is_anomaly']),
                'anomaly_reason': row['anomaly_reason'],
                'llm_category': None,
                'llm_raw_response': None,
                'llm_failed': False
            })

        # 6. Call LLM for Category Classification (modifies list in-place)
        classified_txns = classify_categories(transactions_list)

        # 7. Write all transactions to the database
        for t in classified_txns:
            txn_model = Transaction(
                job_id=job_id,
                txn_id=t['txn_id'],
                date=t['date'],
                merchant=t['merchant'],
                amount=t['amount'],
                currency=t['currency'],
                status=t['status'],
                category=t['category'],
                account_id=t['account_id'],
                notes=t['notes'],
                is_anomaly=t['is_anomaly'],
                anomaly_reason=t['anomaly_reason'],
                llm_category=t['llm_category'],
                llm_raw_response=t['llm_raw_response'],
                llm_failed=t['llm_failed']
            )
            db.add(txn_model)
        
        db.commit()

        # 8. Calculate statistics & generate LLM summary report
        total_inr = df_clean[df_clean['currency'] == 'INR']['amount'].sum() if 'currency' in df_clean.columns else 0.0
        total_usd = df_clean[df_clean['currency'] == 'USD']['amount'].sum() if 'currency' in df_clean.columns else 0.0
        
        try:
            # Get top 3 merchants list by transaction count
            top_merchants_list = df_clean['merchant'].value_counts().head(3).index.tolist()
        except Exception:
            top_merchants_list = []

        anomaly_count = len(df_clean[df_clean['is_anomaly'] == True])

        # Generate Gemini Summary
        summary_result = generate_summary(df_clean)

        summary = JobSummary(
            job_id=job_id,
            total_spend_inr=float(total_inr),
            total_spend_usd=float(total_usd),
            top_merchants=top_merchants_list,
            anomaly_count=anomaly_count,
            narrative=summary_result.get('narrative'),
            risk_level=summary_result.get('risk_level', 'medium')
        )
        db.add(summary)

        # 9. Mark Job as Completed
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        db.commit()
        print(f"Job ID: {job_id} processing completed successfully.")

    except Exception as e:
        print(f"Exception encountered during job processing: {e}")
        db.rollback()
        job.status = "failed"
        job.error_message = str(e)
        db.commit()

    finally:
        db.close()
