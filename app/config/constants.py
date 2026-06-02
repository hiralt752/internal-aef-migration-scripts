"""
Extraction Configuration

IMPORTANT

Do not increase BATCH_SIZE above 500.

During testing larger batches resulted in
unexpected API instability and intermittent
404 responses.

500 should be considered the safe upper limit.
"""

CONCURRENT_REQUESTS = 50

MAX_RETRIES = 5

SAVE_EVERY = 1000

BATCH_SIZE = 500