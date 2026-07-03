from image_resolution_engine.analyzers.mcq import analyze_mcq
from image_resolution_engine.analyzers.fib import analyze_fib
from image_resolution_engine.analyzers.dropdown import analyze_dropdown
from image_resolution_engine.analyzers.dnd import analyze_dnd
from image_resolution_engine.analyzers.matching import analyze_matching
# Fast dict lookup instead of if-elif chain
_ROUTER = {
    "MULTIPLE_CHOICE": analyze_mcq,
    "MULTIPLE_SELECTION": analyze_mcq,
    "FILL_IN_THE_BLANK": analyze_fib,
    "SELECT_A_BLANK": analyze_dropdown,
    "FILL_IN_THE_BLANK_DRAG_DROP":analyze_dnd,
    "IMAGE_LABELLING_DRAG_DROP":analyze_dnd,
    "MATCHING": analyze_matching,
}


def analyze_question(data, q_type, category):
    fn = _ROUTER.get(q_type)
    if not fn:
        return None
        
    res = fn(data, q_type, category)
    if not res:
        return None
        
    audios = []
    videos = []
    
    seen_audios = set()
    seen_videos = set()
    seen_images = set()
    
    for list_key in ("question_images", "option_images", "image_audit"):
        items = res.get(list_key) or []
        filtered_items = []
        for item in items:
            src = item.get("src")
            if not src:
                continue
            content_type = item.get("content_type", "IMAGE")
            if content_type == "AUDIO":
                item.pop("width", None)
                item.pop("height", None)
                if src not in seen_audios:
                    seen_audios.add(src)
                    audios.append(item)
            elif content_type == "VIDEO":
                if src not in seen_videos:
                    seen_videos.add(src)
                    videos.append(item)
            else:
                if src not in seen_images:
                    seen_images.add(src)
                    filtered_items.append(item)
        res[list_key] = filtered_items
        
    res["question_audios"] = audios
    res["question_videos"] = videos
    
    return res