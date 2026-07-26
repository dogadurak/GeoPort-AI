import pandas as pd

# Path to our 1-day filtered test file
CSV_PATH = "data/storebaelt_2026-06-15.csv"

def test_single_day_data() -> None:
    print(f"Loading data from {CSV_PATH}...\n")
    df = pd.read_csv(CSV_PATH)
    
    print("--- Basic Info ---")
    print(f"Total Rows (Ping count): {len(df)}")
    print(f"Total Unique Ships (MMSI): {df['MMSI'].nunique()}\n")
    
    print("--- Columns Present ---")
    print(df.columns.tolist())
    print("\n")
    
    print("--- Bounding Box Verification ---")
    # Expected: Lat 55.0 to 55.6, Lon 10.5 to 11.3
    print(f"Latitude Range:  {df['Latitude'].min():.4f} to {df['Latitude'].max():.4f}")
    print(f"Longitude Range: {df['Longitude'].min():.4f} to {df['Longitude'].max():.4f}\n")
    
    print("--- Sample Data (First 3 Rows) ---")
    print(df.head(3).to_string())

if __name__ == "__main__":
    test_single_day_data()
    