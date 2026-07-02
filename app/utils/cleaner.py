import pandas as pd
from datetime import datetime

def clean_transaction_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans messy CSV transaction data:
    - Standardizes date formats to ISO 8601 (YYYY-MM-DD)
    - Generates unique placeholder IDs for missing txn_ids
    - Normalizes currencies and status to uppercase
    - Cleans and converts transaction amounts to floats
    - Fills blank categories with 'Uncategorised'
    - Removes duplicate rows
    - Drops rows without amount or date
    - Resets dataframe index
    """
    
    # 1. Create a copy to prevent modifying original dataframe views
    df = df.copy()

    # 2. Clean amounts - remove $ prefix and any whitespace, convert to numeric
    if 'amount' in df.columns:
        df['amount'] = df['amount'].astype(str).str.replace('$', '', regex=False).str.strip()
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        
    # 3. Clean dates - parse DD-MM-YYYY and YYYY/MM/DD, output ISO 8601
    def parse_date(date_str):
        if pd.isna(date_str):
            return None
        date_str = str(date_str).strip()
        for fmt in ("%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    if 'date' in df.columns:
        df['date'] = df['date'].apply(parse_date)

    # 4. Drop rows that have missing critical columns (amount or date)
    df = df.dropna(subset=['amount', 'date'])

    # 5. Normalize casing
    if 'status' in df.columns:
        df['status'] = df['status'].astype(str).str.strip().str.upper()
    if 'currency' in df.columns:
        df['currency'] = df['currency'].astype(str).str.strip().str.upper()

    # 6. Fill missing categories with 'Uncategorised'
    if 'category' in df.columns:
        df['category'] = df['category'].fillna('Uncategorised')
        df.loc[df['category'].astype(str).str.strip() == "", 'category'] = 'Uncategorised'

    # 7. Remove exact duplicate rows
    df = df.drop_duplicates()

    # 8. Reset index to ensure a continuous range from 0 to N-1
    df = df.reset_index(drop=True)

    # 9. Handle missing txn_id with unique identifier placeholders (e.g. UNKNOWN_0)
    if 'txn_id' in df.columns:
        for idx in range(len(df)):
            val = df.at[idx, 'txn_id']
            if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan":
                df.at[idx, 'txn_id'] = f"UNKNOWN_{idx}"

    return df
