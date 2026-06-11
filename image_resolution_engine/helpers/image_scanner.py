from bs4 import BeautifulSoup
from typing import Any, Dict, List
import re

IMG_PATTERN = re.compile(r'<img[^>]*>', re.IGNORECASE | re.MULTILINE)
SVG_DATA = "data:image/svg+xml"


def _extract_images_from_html(html: str, key_path: str) -> List[Dict]:
    if not html or not isinstance(html, str):
        return []
    
    if '<img' not in html:
        return []
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src or src.startswith(SVG_DATA):
                continue
            
            results.append({
                "key": key_path,
                "src": src,
                "width": img.get("width"),
                "height": img.get("height"),
            })
        
        return results
    except Exception:
        return []


def scan_json(obj: Any, path: str = "") -> List[Dict]:

    results = []
    stack = [(obj, path)]

    while stack:
        node, cur_path = stack.pop()

        if isinstance(node, dict):
            # Inline iteration - faster than helper function
            for k, v in node.items():
                new_path = f"{cur_path}.{k}" if cur_path else k
                stack.append((v, new_path))

        elif isinstance(node, list):
            for i, item in enumerate(node):
                stack.append((item, f"{cur_path}[{i}]"))

        elif isinstance(node, str):
            if "<img" in node:
                results.extend(_extract_images_from_html(node, cur_path))

    return results


def has_images(obj: Any) -> bool:
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for v in node.values():
                stack.append(v)
        elif isinstance(node, list):
            for item in node:
                stack.append(item)
        elif isinstance(node, str) and "<img" in node:
            return True
    return False