import json
import orjson

# Try to use orjson (3x faster) if available, fallback to json
try:
    def load_json(file_path: str):
        """Ultra-fast JSON loading with orjson."""
        try:
            with open(file_path, "rb") as f:
                return orjson.loads(f.read())
        except Exception:
            return None
except ImportError:
    # Fallback to standard json
    def load_json(file_path: str):
        """Standard JSON loading."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None