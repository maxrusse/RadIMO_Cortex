# Skill-Modality Usage Logging

## Overview

The usage logging system tracks how often each skill-modality combination is used in the RadIMO Cortex application. This data is tracked per work unit (combinations of entries per day) rather than per user, allowing you to monitor tool usage patterns and compare against actual work entries from other data sources.

## Features

- **Automatic Tracking**: Every assignment request automatically logs the skill-modality combination used
- **Daily Aggregation**: Usage is tracked per day with automatic reset and export
- **CSV Export**: Daily statistics are exported to CSV files for easy analysis
- **Scheduled Export**: Automatic export at 7:30 AM daily (or when the first assignment after that time occurs)
- **API Access**: RESTful API endpoints for viewing stats and manual export

## How It Works

### Automatic Logging

When a worker is assigned via the API endpoints:
- `GET /api/<modality>/<role>`
- `GET /api/<modality>/<role>/strict`

The system automatically:
1. Records the skill-modality combination used (e.g., `Notfall + ct`)
2. Increments the daily counter for that combination
3. Checks if it's time for the daily export (7:30 AM)

### Data Structure

The system tracks usage as a simple counter per skill-modality combination:

```
(skill, modality) → count
```

Example:
```
('Notfall', 'ct') → 15
('Privat', 'ct') → 8
('MSK', 'mr') → 12
```

### CSV Export Format

Usage statistics are exported to a single CSV file in **wide format** with one row per day.

**Filename**: `logs/usage_stats/usage_stats.csv`

**CSV Structure**:
- **First Column**: `date` (YYYY-MM-DD format)
- **Remaining Columns**: One column for each skill-modality combination in format `Skill_modality`
  - Examples: `Notfall_ct`, `Privat_mr`, `MSK_xray`, `Cardvask_ct`
  - All columns are always present, with value 0 if not used that day

**Example**:
```csv
date,Notfall_ct,Notfall_mr,Privat_ct,Privat_mr,MSK_ct,MSK_mr,Cardvask_ct,Cardvask_mr,...
2025-12-22,15,8,5,2,3,12,5,1,...
2025-12-23,18,6,7,3,2,10,4,0,...
2025-12-24,12,10,6,4,5,15,3,2,...
```

**Benefits of Wide Format**:
- One row per day = easy to track trends over time
- All skill-modality combinations in a single row = simple daily comparison
- Perfect for spreadsheet analysis, pivot tables, and data visualization
- Easy to join with other daily data sources

### Daily Reset

The system automatically exports and resets counters when:
1. **Date Changes**: When the first assignment request occurs on a new day
2. **Scheduled Time**: At or after 7:30 AM (checked with each assignment)

The export preserves the previous day's data to a CSV file before resetting.

## API Endpoints

All endpoints require authentication (via the `@requires_auth` decorator).

### Get Current Usage Statistics

```
GET /api/usage-stats/current
```

Returns the current day's usage statistics in JSON format.

**Response Example**:
```json
{
  "date": "2025-12-22",
  "total_combinations": 8,
  "total_usages": 45,
  "stats": [
    {
      "skill": "Notfall",
      "modality": "ct",
      "count": 15
    },
    {
      "skill": "Privat",
      "modality": "ct",
      "count": 8
    },
    ...
  ]
}
```

### Manual Export

```
POST /api/usage-stats/export
```

Manually triggers an export of current usage statistics to CSV without resetting counters.

**Note**: In wide format, this appends the current day's data as a new row to the single CSV file. If you export multiple times on the same day, you'll get multiple rows with the same date (showing different counts as usage accumulates).

**Response Example**:
```json
{
  "success": true,
  "message": "Usage statistics exported successfully (appended to CSV)",
  "file_path": "logs/usage_stats/usage_stats.csv",
  "date": "2025-12-22",
  "note": "Data appended as new row in wide format CSV"
}
```

### Reset Statistics

```
POST /api/usage-stats/reset
```

Resets the current usage counters without exporting (use with caution).

**Response Example**:
```json
{
  "success": true,
  "message": "Usage statistics reset successfully"
}
```

### Get CSV File Info

```
GET /api/usage-stats/file
```

Gets information about the usage statistics CSV file (single file in wide format).

**Response Example**:
```json
{
  "success": true,
  "exists": true,
  "filename": "usage_stats.csv",
  "path": "logs/usage_stats/usage_stats.csv",
  "size_bytes": 8192,
  "total_days": 30,
  "dates": ["2025-11-23", "2025-11-24", ..., "2025-12-22"],
  "date_range": {
    "first": "2025-11-23",
    "last": "2025-12-22"
  }
}
```

## Use Cases

### Monitor Tool Usage vs Actual Work

The wide format makes it easy to compare with your actual work entry data:

1. Open the `logs/usage_stats/usage_stats.csv` file
2. Load your work entry data from your external source (also in wide format with same columns)
3. Join/merge the data on `date` column
4. For each skill-modality column, calculate: `tool_clicks / actual_work_entries`

**Example Analysis** (in Excel/Python/R):
```
Date        | Notfall_ct (Tool) | Notfall_ct (Actual) | Ratio
------------|-------------------|---------------------|-------
2025-12-22  | 15                | 20                  | 0.75
2025-12-23  | 18                | 18                  | 1.00
2025-12-24  | 12                | 15                  | 0.80
```

This helps you understand:
- Which skill-modality combinations are most frequently used
- Whether the tool is being used for all work or only specific cases
- Usage patterns over time
- Days where tool usage doesn't match actual work (potential training needs)

### Track Usage Trends

With wide format, trend analysis is straightforward:
- Each row is a day, so plotting over time is simple
- Compare columns side-by-side to see which skill-modality combinations trend together
- Identify weekly/monthly patterns using date column
- Easily create time-series charts in Excel or any data visualization tool

**Example**:
```python
import pandas as pd
import matplotlib.pyplot as plt

# Load the CSV
df = pd.read_csv('logs/usage_stats/usage_stats.csv', parse_dates=['date'])

# Plot Notfall usage across all modalities over time
df.plot(x='date', y=['Notfall_ct', 'Notfall_mr', 'Notfall_xray'], figsize=(12,6))
plt.title('Notfall Usage Trends by Modality')
plt.ylabel('Number of Assignments')
plt.show()
```

### Capacity Planning

Use the usage data to:
- Identify which skill-modality combinations need more staffing
- Optimize worker schedules based on actual demand
- Predict future resource needs

## File Locations

- **CSV File**: `logs/usage_stats/usage_stats.csv` (single file, wide format, one row per day)
- **Module**: `lib/usage_logger.py`
- **Integration**: `routes.py` (usage stats endpoints at lines 1126-1229)

## Configuration

No additional configuration is required. The system automatically:
- Creates the `logs/usage_stats/` directory if it doesn't exist
- Handles file naming and rotation
- Manages daily reset timing

## Technical Details

### Thread Safety

The usage logger uses a threading lock to ensure thread-safe operations when:
- Recording usage
- Exporting data
- Resetting counters

### Data Persistence

Current usage data is stored in memory only. Daily exports persist to CSV files. If the application restarts during the day, current day's data will be lost (not exported). To prevent this, you can:
1. Set up automatic regular exports via cron
2. Call the manual export endpoint before restart
3. Implement automatic export on application shutdown (future enhancement)

### Performance Impact

The logging system is designed to be lightweight:
- In-memory counter increments (O(1) operation)
- Daily export happens once per day
- No database queries or external API calls
- Minimal overhead per assignment request

## Troubleshooting

### No CSV File Generated

**Issue**: No CSV file appears in `logs/usage_stats/`

**Solutions**:
- Check that assignments are being made (usage is only recorded when workers are assigned)
- Verify the `logs/usage_stats/` directory exists and is writable
- Check the application logs for export errors

### Missing Data

**Issue**: Some usage data seems to be missing

**Solutions**:
- Check if the application was restarted mid-day (current data is lost on restart until next export)
- Verify that the date change logic is working correctly
- Check the dates in the CSV file to see which days have been exported

### Duplicate Date Rows

**Issue**: Same date appears multiple times in the CSV

**Solutions**:
- This can happen if you manually export multiple times on the same day using `/api/usage-stats/export`
- The automatic daily export (triggered by date change) only exports once per day
- When analyzing, either:
  - Use only the last row for each date (most recent counts)
  - Filter to dates before today (completed days only)
  - Remove duplicates: `df.drop_duplicates(subset='date', keep='last')`
