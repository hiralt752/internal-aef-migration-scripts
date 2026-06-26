import json

with open(
    "cache/uploaded_files.json",
    encoding="utf-8"
) as f:

    data = json.load(f)

print(json.dumps(
    data,
    indent=2,
    ensure_ascii=False
))