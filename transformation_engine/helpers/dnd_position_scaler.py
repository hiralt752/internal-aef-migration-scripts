"""
Helper module for scaling IMD-DND (IMAGE_LABELLING_DRAG_DROP) target position coordinates.
Scales normalized decimal coordinates (x, y in [0, 1]) to target viewport pixel coordinates using aspect ratio containment.
"""

def calculate_imd_dnd_target_position(
    x_decimal: float,
    y_decimal: float,
    raw_bg_width: float = None,
    raw_bg_height: float = None,
    target_viewport_width: int = 560,
    target_viewport_height: int = 315,
    target_box_width: int = 120
) -> dict:
    """
    Scales normalized decimal coordinates (0..1) to target display viewport pixel coordinates.
    Handles percentage dimensions (e.g. width=100%) and preserves aspect ratio containment.
    Target coordinates in QB API payloads are IMAGE-RELATIVE top-left offsets.
    """
    if x_decimal is None or y_decimal is None:
        return {"top": 0, "left": 0, "width": target_box_width}

    # Clamp decimal inputs to valid [0, 1] bounds
    x = max(0.0, min(1.0, float(x_decimal)))
    y = max(0.0, min(1.0, float(y_decimal)))

    # Convert raw dimensions to float if present
    bg_w = float(raw_bg_width) if raw_bg_width is not None else None
    bg_h = float(raw_bg_height) if raw_bg_height is not None else None

    # Guard against invalid or zero raw dimensions
    if not bg_w or not bg_h or bg_w <= 0 or bg_h <= 0:
        left_px = round(x * target_viewport_width)
        top_px = round(y * target_viewport_height)
        return {"top": max(0, top_px), "left": max(0, left_px), "width": target_box_width}

    # Aspect Ratio Containment Scaling with Viewport Center Offset
    src_aspect = bg_w / bg_h
    target_aspect = target_viewport_width / target_viewport_height

    if src_aspect > target_aspect:
        # Source is wider -> scale by width
        scale = target_viewport_width / bg_w
        rendered_w = target_viewport_width
        rendered_h = bg_h * scale
        offset_x = 0.0
        offset_y = (target_viewport_height - rendered_h) / 2.0
    else:
        # Source is taller -> scale by height
        scale = target_viewport_height / bg_h
        rendered_w = bg_w * scale
        rendered_h = target_viewport_height
        offset_x = (target_viewport_width - rendered_w) / 2.0
        offset_y = 0.0

    visual_x = (x * bg_w) * scale + offset_x
    visual_y = (y * bg_h) * scale + offset_y

    # Source (x, y) coordinates represent drop target center.
    # Shift from CENTER to TOP-LEFT corner for 120px wide x 56px high target box:
    target_box_height = 56
    left_px = round(visual_x - (target_box_width / 2.0))
    top_px = round(visual_y - (target_box_height / 2.0))

    return {
        "top": max(0, top_px),
        "left": max(0, left_px),
        "width": target_box_width
    }
