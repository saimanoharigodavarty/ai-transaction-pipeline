import pandas as pd

def flag_anomalies(df: pd.DataFrame) -> list:
    """
    Identifies anomalous transactions:
    1. Statistical Outliers: transaction amount exceeds 3x the median transaction amount of its account.
    2. Domestic Currency Mismatch: currency is USD but merchant is a domestic Indian brand.
    
    Returns a list of dictionaries with structure:
    [{'index': row_index, 'reason': reason_string}]
    """
    anomalies = []
    domestic_brands = ['swiggy', 'ola', 'irctc']

    for idx, row in df.iterrows():
        reason = None
        account_id = row.get('account_id')
        amount = row.get('amount')
        currency = row.get('currency')
        merchant = str(row.get('merchant', '')).strip()

        # Rule 1: Statistical outlier check (3x account median)
        if pd.notna(account_id) and pd.notna(amount):
            # Get all transaction amounts for this specific account
            account_amounts = df[df['account_id'] == account_id]['amount']
            account_median = account_amounts.median()
            
            if pd.notna(account_median) and amount > (account_median * 3):
                reason = f"Statistical Outlier: Amount {amount} exceeds 3x account median ({account_median * 3:.2f})"

        # Rule 2: Domestic brand + USD currency check
        if pd.notna(currency) and currency == 'USD':
            if any(brand in merchant.lower() for brand in domestic_brands):
                reason = f"Currency Mismatch: USD transaction with domestic brand '{merchant}'"

        if reason:
            anomalies.append({
                'index': idx,
                'reason': reason
            })

    return anomalies
