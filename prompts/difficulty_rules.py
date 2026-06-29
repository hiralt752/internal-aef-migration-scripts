DIFFICULTY_RULES = """
Difficulty values:
- Access=foundational or entry-level understanding needed to start learning the concept.
- Expectation=secure grade-level understanding aligned to the expected lesson objective.
- Extension=advanced or enrichment-level understanding beyond the expected lesson objective.

Difficulty policy:
- Assign difficultyLevel for every subject.
- If lesson content is supplied, use lesson content together with the question to determine difficultyLevel.
- If lesson content is not supplied, use the question content only.
- Return a short difficultyReason explaining the assigned difficultyLevel.
"""
