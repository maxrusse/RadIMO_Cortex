import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime
from config import APP_CONFIG
from data_manager import build_working_hours_from_medweb

def verify_vendor_b():
    csv_path = 'test_data/test_vendor_b.csv'
    target_date = datetime(2025, 12, 10)
    
    # Manually inject vendor_b config since the rest of the app might still be biased towards 'medweb' name
    # In a real scenario, we'd pass the correct vendor config to the loader
    vendor_b_config = {
        'medweb_mapping': APP_CONFIG['vendor_mappings']['vendor_b'],
        'modalities': APP_CONFIG['modalities'],
        'skills': APP_CONFIG['skills'],
        'shift_times': APP_CONFIG['shift_times']
    }
    
    print(f"Testing load from {csv_path} for {target_date.date()} (Vendor B)...")
    
    try:
        results = build_working_hours_from_medweb(csv_path, target_date, vendor_b_config)
        
        if not results:
            print("FAILED: No data loaded for Vendor B.")
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
    verify_vendor_b()
