import google.generativeai as genai
import json
import time
import re
from app.config import GEMINI_API_KEY

# Configure Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("Warning: GEMINI_API_KEY is not set. LLM calls will use fallback mock logic.")

def retry_with_backoff(func, retries=3, initial_delay=2, backoff_factor=2):
    """
    Executes a function with exponential backoff retries.
    """
    delay = initial_delay
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            if attempt == retries - 1:
                print(f"All {retries} retries failed. Error: {e}")
                raise e
            print(f"LLM call failed (attempt {attempt + 1}/{retries}). Retrying in {delay} seconds... Error: {e}")
            time.sleep(delay)
            delay *= backoff_factor

def clean_json_response(text: str) -> str:
    """
    Cleans markdown wrappers (like ```json ... ```) from LLM response texts
    to prepare for standard JSON parsing.
    """
    if not text:
        return ""
    text = text.strip()
    # Strip markdown block formatting if present
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text

def classify_categories(transactions: list) -> list:
    """
    Batches and classifies uncategorized transactions using Gemini 1.5 Flash.
    Updates the list in-place and sets 'llm_category', 'llm_raw_response', and 'llm_failed'.
    """
    # Identify indices of transactions needing classification
    uncategorized_idx = [i for i, t in enumerate(transactions) if t.get('category') == 'Uncategorised']
    
    if not uncategorized_idx:
        return transactions

    # We batch them in sizes of 15 to keep it optimal
    batch_size = 15
    
    for start_i in range(0, len(uncategorized_idx), batch_size):
        batch_indices = uncategorized_idx[start_i : start_i + batch_size]
        batch_txns = [transactions[idx] for idx in batch_indices]
        
        # Build prompt listing each transaction's index, merchant, and notes
        batch_lines = []
        for i, t in enumerate(batch_txns):
            merchant = t.get('merchant', 'Unknown')
            notes = t.get('notes', '')
            batch_lines.append(f"Index: {i} | Merchant: {merchant} | Notes: {notes}")
        
        batch_text = "\n".join(batch_lines)
        
        prompt = f"""
You are a financial transaction classification assistant.
Classify each transaction below into exactly one of these standard categories:
- Food
- Shopping
- Travel
- Transport
- Utilities
- Cash Withdrawal
- Entertainment
- Other

Transactions:
{batch_text}

Respond STRICTLY in JSON format where the keys are the string representation of the Index (e.g. "0", "1") and the values are the matching Category.
Do not output any markdown headers, conversational text, or details outside of the JSON payload.
Example response:
{{
  "0": "Food",
  "1": "Utilities"
}}
"""

        def make_call():
            if not GEMINI_API_KEY:
                raise ValueError("Gemini API key is not configured.")
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt, timeout=15)
            if not response or not response.text:
                raise ValueError("Empty response received from Gemini API.")
            return response.text

        try:
            # Call LLM with exponential backoff retry logic
            raw_text = retry_with_backoff(make_call, retries=3)
            cleaned_text = clean_json_response(raw_text)
            classifications = json.loads(cleaned_text)
            
            # Map classifications back to original transaction list
            for i, t in enumerate(batch_txns):
                assigned_category = classifications.get(str(i), 'Other')
                # Make sure the category is one of the valid ones, default to 'Other'
                valid_categories = ['Food', 'Shopping', 'Travel', 'Transport', 'Utilities', 'Cash Withdrawal', 'Entertainment', 'Other']
                if assigned_category not in valid_categories:
                    assigned_category = 'Other'
                
                t['category'] = assigned_category
                t['llm_category'] = assigned_category
                t['llm_raw_response'] = raw_text
                t['llm_failed'] = False
                
        except Exception as e:
            # Gracefully handle failures by marking llm_failed = True and fallback to 'Other'
            print(f"Batch classification failed: {e}")
            for t in batch_txns:
                t['category'] = 'Other'
                t['llm_category'] = 'Other'
                t['llm_raw_response'] = f"Error during classification: {str(e)}"
                t['llm_failed'] = True

    return transactions

def generate_summary(df) -> dict:
    """
    Sends aggregate statistics of the processed job to Gemini 1.5 Flash
    to generate a narrative summary and risk assessment.
    """
    total_inr = df[df['currency'] == 'INR']['amount'].sum() if 'currency' in df.columns else 0
    total_usd = df[df['currency'] == 'USD']['amount'].sum() if 'currency' in df.columns else 0
    
    try:
        top_merchants_list = df['merchant'].value_counts().head(3).index.tolist()
    except:
        top_merchants_list = []
        
    anomaly_count = len(df[df['is_anomaly'] == True]) if 'is_anomaly' in df.columns else 0

    prompt = f"""
You are a financial risk analyst. Analyze the following transaction summary statistics:
- Total spend in Indian Rupees (INR): {total_inr:.2f}
- Total spend in US Dollars (USD): {total_usd:.2f}
- Top 3 Merchants: {", ".join(top_merchants_list)}
- Flagged Anomalies Count: {anomaly_count}

Generate a JSON response containing:
1. "narrative": A 2-to-3 sentence professional description summarizing the spending behavior and any notable concerns or risks flagged.
2. "risk_level": A single rating: "low", "medium", or "high".

Respond STRICTLY in JSON format with keys "narrative" and "risk_level".
Do not output any introductory or explanation text.
Example response:
{{
  "narrative": "The user spending shows regular patterns with top merchants. However, a domestic transaction in USD suggests potential currency settings errors.",
  "risk_level": "medium"
}}
"""

    def make_call():
        if not GEMINI_API_KEY:
            raise ValueError("Gemini API key is not configured.")
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt, timeout=15)
        if not response or not response.text:
            raise ValueError("Empty response received from Gemini API.")
        return response.text

    try:
        # Call LLM with exponential backoff retry logic
        raw_text = retry_with_backoff(make_call, retries=3)
        cleaned_text = clean_json_response(raw_text)
        result = json.loads(cleaned_text)
        
        # Verify structure
        if "narrative" in result and "risk_level" in result:
            return {
                "narrative": result["narrative"],
                "risk_level": str(result["risk_level"]).strip().lower()
            }
        raise ValueError("Invalid JSON keys in Gemini response.")
        
    except Exception as e:
        print(f"LLM summary generation failed: {e}")
        # Graceful fallback summary
        return {
            "narrative": f"Transaction processing completed. Spending narrative is temporarily unavailable due to LLM service connectivity issues.",
            "risk_level": "medium"
        }
