WIDGET_LAYOUT_MAP = {

    "MCQ (image+2options)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9"
    },
    "MCQ (image+4options)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9"
    },
    "MCQ (2imageoptions)": {
        "max_width": 600,
        "max_height": 133,
        "ratio": None
    },
    "MCQ (2imageoptions-withoutLabel)": {
        "max_width": 600,
        "max_height": 133,
        "ratio": None
    },
    "MCQ (text/image+2imageoptions)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9",
        "option_width": 600,
        "option_height": 133
    },
    "MCQ (3imageoptions)": {
        "max_width": 600,
        "max_height": 208,
        "ratio": None
    },
    "MCQ (3imageoptions-withoutLabel)": {
        "max_width": 600,
        "max_height": 208,
        "ratio": None
    },
    "MCQ (text/image+3imageoptions)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9",
        "option_width": 600,
        "option_height": 208,
    },
    "MCQ (4imageoptions)": {
        "max_width": 600,
        "max_height": 288,
        "ratio": None
    },
    "MCQ (4imageoptions-withoutLabel)": {
        "max_width": 600,
        "max_height": 288,
        "ratio": None
    },
    "MCQ (text/image+4imageoptions)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9",
        "option_width": 600,
        "option_height": 288
    },
    # NEWLY DETECTED: Split Screen MCQ Layouts
    "MCQ Split Screen (halfimage)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9"
    },
    "MCQ Split Screen (fullimage)": {
        "max_width": 600,
        "max_height": 800,
        "ratio": "3:4"
    },

    # ==========================================
    # FILL IN THE BLANK (FIB) VARIANTS
    # ==========================================
    "FIB (fullimage)": {
        "max_width": 600,
        "max_height": 800,
        "ratio": "3:4"
    },
    "FIB (halfimage)": {
        "max_width": 600,
        "max_height": 450,
        "ratio": "4:3"
    },
    "FIB Blanks": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9"
    },
    # ==========================================
    # DROPDOWN / SELECT_BLANK VARIANTS
    # ==========================================

    "Dropdown (2cards)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9"
    },

    "Dropdown (3cards)": {
        "max_width": 600,
        "max_height": 450,
        "ratio": "4:3"
    },

    "Dropdown (4cards)": {
        "max_width": 600,
        "max_height": 450,
        "ratio": "4:3"
    },

    "Dropdown (halfimage)": {
        "max_width": 600,
        "max_height": 450,
        "ratio": "4:3",
        "option_width": 440,
        "option_height": 330
    },
    "Drag and Drop (mainimage)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9",
        "main_image_width": 560,
        "main_image_height": 315
    },
    "Drag and Drop (4imageoptions)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "16:9",
        "main_image_width": 560,
        "main_image_height": 315,
        "option_image_width": 120,
        "option_image_height": 120,
        "option_ratio": "1:1"
    },
    "Drag and Drop (SplitScreenImage)": {
        "max_width": 600,
        "max_height": 450,
        "ratio": "4:3",
        "main_image_width": 252,
        "main_image_height": 189
    },
    "Matching (2imageoptions)": {
        "max_width": 224,
        "max_height": 168,
        "ratio": "4:3",
        "option_width": 224,
        "option_height": 168
    },

    "Matching (3imageoptions)": {
        "max_width": 128,
        "max_height": 96,
        "ratio": "4:3",
        "option_width": 128,
        "option_height": 96
    },
    "Open Ended (image+inputbox)": {
        "max_width": 600,
        "max_height": 800,
        "ratio": "3:4",
        "image_width": 400,
        "image_height": 533
    },
    "See Why/Need Help (mainimage)": {
        "max_width": 600,
        "max_height": 388,
        "ratio": "3:4",
        "image_width": 291,
        "image_height": 388
    },
    "See Why/Need Help (twoimages)": {
        "max_width": 600,
        "max_height": 338,
        "ratio": "3:4",
        "image_width": 254,
        "image_height": 338
    }
}


def get_widget_resolution(widget_type: str):
    return WIDGET_LAYOUT_MAP.get(widget_type, {
        "max_width": 600,
        "max_height": 338,
        "ratio": "fallback"
    })