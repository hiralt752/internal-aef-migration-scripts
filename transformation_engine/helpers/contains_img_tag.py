from bs4 import BeautifulSoup


def contains_img_tag(data):
    """
    Recursively scans any JSON structure and returns True
    if an HTML string contains an <img> tag.
    """

    if data is None:
        return False

    # String value
    if isinstance(data, str):
        try:
            soup = BeautifulSoup(data, "html.parser")
            return soup.find("img") is not None
        except Exception:
            return False

    # Dictionary
    if isinstance(data, dict):
        return any(
            contains_img_tag(value)
            for value in data.values()
        )

    # List / Tuple
    if isinstance(data, (list, tuple)):
        return any(
            contains_img_tag(item)
            for item in data
        )

    return False