from analyzers.mcq import analyze_mcq
from analyzers.fib import analyze_fib
from analyzers.dropdown import analyze_dropdown
from analyzers.dnd import analyze_dnd
from analyzers.matching import analyze_matching
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
    return fn(data, q_type, category) if fn else None   