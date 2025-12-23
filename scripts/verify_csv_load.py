import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime
from config import APP_CONFIG
from data_manager import build_working_hours_from_medweb

def verify():
    csv_path = 'test_data/medweb_test_multiday.csv'
    target_date = datetime(2025, 12, 10)
    
    print(f"Testing load from {csv_path} for {target_date.date()}...")
    
    try:
        results = build_working_hours_from_medweb(csv_path, target_date, APP_CONFIG)
        
        if not results:
            print("FAILED: No data loaded.")
            return
            
        print(f"SUCCESS: Loaded data for modalities: {list(results.keys())}")
        for mod, df in results.items():
            print(f"  {mod}: {len(df)} rows")
            if not df.empty:
                print(f"    Sample: {df.iloc[0]['PPL']} - {df.iloc[0]['start_time']}-{df.iloc[0]['end_time']}")
                
    except Exception as e:
        print(f"FAILED with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify()
