BASE_CLASSIFICATION_PROMPT = """
Classify the educational intent of the question.
Use the supplied question data. If lesson content is supplied, use it for difficulty classification. If curriculum files are attached, choose outcomeKeys only from those files.
Return valid JSON only. No markdown or extra text.
"""
