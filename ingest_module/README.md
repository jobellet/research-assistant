# Ingest Module

The `ingest_module/` is responsible for monitoring a directory for scientific PDFs, hashing them, and storing them in a unique location to prevent redundant processing.

## Features
- **SHA-256 Hashing**: Every file is uniquely identified based on its binary content.
- **Automated Monitoring**: Detects new files in the `inbox/` using the `watchdog` library.
- **Structure Logic**: Creates a folder at `library/<sha256>/` for each ingested document.

## Setup & Dependencies
Ensure you have the required dependencies installed:
```bash
pip install watchdog
```

## Usage

### Run the Monitor
To start the background monitor that watches the `inbox/` folder:
```bash
python3 ingest_module/monitor.py
```

### Manual Ingestion
You can also import the `process_file` function in your own scripts:
```python
from ingest_module import process_file
process_file("path/to/paper.pdf", "library/")
```

## How it Works
1. **Inbox**: Drop any PDF into the `inbox/` directory.
2. **Hash**: The system calculates the SHA-256 hash of the file.
3. **Move**: The file is moved to `library/<hash>/<original_filename>.pdf`.
4. **Cleanup**: The file is removed from `inbox/` upon successful ingestion.

## Testing
A test script is available in the `scratch/` directory to verify the logic independently:
```bash
python3 scratch/test_ingestion.py
```
This script creates a dummy PDF, processes it, and verifies the resulting directory structure.
