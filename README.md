# Receipt Ingestion Pipeline

A Python tool that automatically processes receipt images from Dropbox, extracts data via Azure OCR, and imports transactions into Actual Budget.

## How It Works

1. Checks Dropbox `/incoming` folder for new receipt images
2. Sends each image to Azure Document Intelligence (prebuilt-receipt model) for OCR
3. Extracts: merchant name, total, date, card number, Apple Pay account name
4. Maps the card/account to an Actual Budget account using `cc_accounts.csv`
5. Imports the transaction into Actual Budget via actualpy
6. Moves the file to `/completed` (or `/exception` if account matching fails)
7. Sends a Pushover notification with the result

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Copy the config template and fill in your real values:

```bash
cp config.yaml config.local.yaml
```

Edit `config.local.yaml` with your credentials for Dropbox, Azure, Actual Budget, and Pushover.

### 3. Update account mappings

Edit the `account_mapping` section in your `config.local.yaml` to map your credit card numbers and Apple Pay names to Actual Budget account names.

### 4. Run manually (to test)

```bash
python main.py
```

### 5. Set up cron (for automatic processing)

Run every 15 minutes:

```
*/15 * * * * cd /path/to/receipt-ingestion/python && python main.py >> /var/log/receipt-ingestion.log 2>&1
```

On Windows Task Scheduler, create a task that runs `python main.py` every 15 minutes.

## Project Structure

```
python/
├── main.py              # Entry point — orchestrates the pipeline
├── config.yaml          # Configuration template (includes account mapping)
├── config.local.yaml    # Your real credentials (git-ignored)
├── config_loader.py     # Loads YAML config files
├── dropbox_client.py    # Dropbox SDK wrapper (list, temp links, move)
├── azure_ocr.py         # Azure Document Intelligence OCR
├── account_mapper.py    # Credit card → Actual Budget account lookup
├── actual_budget.py     # Actual Budget transaction import via actualpy
├── pushover_notify.py   # Pushover push notifications
└── requirements.txt     # Python dependencies
```

## Key Differences from n8n Version

- **Dropbox uniqueness**: Uses Dropbox's built-in `autorename` instead of manually prepending timestamps to filenames. If a file with the same name already exists in `/completed` or `/exception`, Dropbox automatically appends ` (1)`, ` (2)`, etc.
- **Azure OCR polling**: Uses a simple `time.sleep()` loop instead of the n8n wait/check/loop pattern.
- **Actual Budget**: Uses the `actualpy` Python library directly instead of shelling out to a Node.js script.
- **All files processed**: Processes all files in `/incoming` per run (the n8n version only processed the first file).
- **Duplicate detection**: Uses the same hash-based `imported_id` as the n8n version for compatibility.

## Dropbox Setup

You'll need a Dropbox app with a refresh token. To get one:

1. Go to https://www.dropbox.com/developers/apps and create an app
2. Set permissions: `files.metadata.read`, `files.metadata.write`, `files.content.read`, `files.content.write`
3. Generate a refresh token (the app key + secret + refresh token go in your config)
