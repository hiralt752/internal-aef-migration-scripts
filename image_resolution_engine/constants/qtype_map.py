# Pre-computed lookup table (frozen dict-like)
QTYPE_MAP = {
    "MULTIPLE_CHOICE": "MCQ",
    "MULTIPLE_SELECTION": "MCQ",
    "FILL_IN_THE_BLANK": "FIB",
    "SELECT_A_BLANK": "Dropdown",
    "FILL_IN_THE_BLANK_DRAG_DROP":"Drag and Drop",
    "IMAGE_LABELLING_DRAG_DROP":"Drag and Drop",
    "MATCHING":"MATCHING"
}


def normalize_qtype(qtype: str) -> str:
    return QTYPE_MAP.get(qtype, qtype)