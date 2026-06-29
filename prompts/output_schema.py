MATH_SCIENCE_OUTPUT_SCHEMA = """
JSON for MATH/SCIENCE:

{
  "topOutcomeKeys": [
    {
      "rank": 1,
      "outcomeKey": "skill-12345",
      "confidence": 0.95,
      "reason": "Short reason why this outcomeKey matches the question."
    },
    {
      "rank": 2,
      "outcomeKey": "skill-67890",
      "confidence": 0.86,
      "reason": "Short reason why this is the second-best match."
    },
    {
      "rank": 3,
      "outcomeKey": "skill-54321",
      "confidence": 0.78,
      "reason": "Short reason why this is the third-best match."
    }
  ],
  "selectedOutcomeKey": "skill-12345",
  "selectedOutcomeReason": "Explain why the highest-confidence outcomeKey was selected as the final curriculum outcome.",
  "bloom": "ANALYZE",
  "bloomReason": "Explain only why this Bloom level was selected.",
  "dok": "DOK2",
  "dokReason": "Explain only why this DOK level was selected.",
  "difficultyLevel": "Expectation",
  "difficultyReason": "Explain only why this difficulty level was selected.",
  "confidence": 0.95
}

Rules:
- Exactly 3 outcomeKey candidates from the attached curriculum files.
- Rank by descending confidence.
- selectedOutcomeKey and confidence must match topOutcomeKeys[0].
- selectedOutcomeReason must say why rank 1 beats ranks 2 and 3.
"""

GENERAL_OUTPUT_SCHEMA = """
JSON for non-MATH/SCIENCE:

{
  "bloom": "UNDERSTAND",
  "bloomReason": "Explain only why this Bloom level was selected.",
  "dok": "DOK1",
  "dokReason": "Explain only why this DOK level was selected.",
  "difficultyLevel": "Expectation",
  "difficultyReason": "Explain only why this difficulty level was selected.",
  "confidence": 0.95
}
"""


ISLAMIC_OUTPUT_SCHEMA = """
JSON for ISLAMIC:

{
  "bloom": "UNDERSTAND",
  "bloomReason": "Explain only why this Bloom level was selected.",
  "dok": "DOK1",
  "dokReason": "Explain why DOK1 applies, or why the question clearly qualifies for the DOK2 exception.",
  "difficultyLevel": "Expectation",
  "difficultyReason": "Explain only why this difficulty level was selected.",
  "confidence": 0.95
}

Rules:
- dok must be DOK1 or DOK2 only.
- Default to DOK1.
- Use DOK2 only for a clear non-foundational application or explanation task.
"""


BLOOM_ONLY_OUTPUT_SCHEMA = """
JSON for ARABIC/SOCIAL:

{
  "bloom": "UNDERSTAND",
  "bloomReason": "Explain only why this Bloom level was selected.",
  "difficultyLevel": "Expectation",
  "difficultyReason": "Explain only why this difficulty level was selected.",
  "confidence": 0.95
}

Do not return dok or dokReason. DOK is assigned deterministically after AI classification.
"""
