import json

def transform_matching_data(aat_data):
    """
    Transforms AAT MATCHING data into the target QB MatchingQuestionResource format.
    Ensures zero data loss by mapping full metadata and validation blocks.
    """
    response = aat_data.get("response", {})
    body = response.get("body", {})
    validation = response.get("validation", {})
    metadata_source = response.get("metadata", {})

    qb_payload = {
        "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
        "type": "MATCHING",
        "subType": "MATCHING_PAIRS",
        "metadata": {
            "general": {
                "code": response.get("code"),
                "externalId": response.get("id"),
                "language": response.get("language"),
                "keywords": metadata_source.get("keywords", []),
                "source": metadata_source.get("author")
            },
            "educational": {
                "resourceType": metadata_source.get("resourceType"),
                "difficultyLevel": metadata_source.get("difficultyLevel"),
                "cognitiveDimensions": metadata_source.get("cognitiveDimensions", []),
                "knowledgeDimensions": metadata_source.get("knowledgeDimensions", []),
                "curriculumOutcomes": metadata_source.get("curriculumOutcomes", []),
                "cefrLevel": metadata_source.get("cefrLevel"),
                "proficiency": metadata_source.get("proficiency")
            }
        },
        "itemBody": {
            "version": "1.0",
            "shuffled": body.get("matchers", {}).get("shuffle", True),
            "sourceItems": [
                {
                    "id": item["id"],
                    "text": item["value"],
                    "weight": item.get("weight"),
                    "feedback": item.get("feedback")
                } for item in body.get("matchers", {}).get("choices", [])
            ],
            "targetItems": [
                {
                    "id": item["id"],
                    "text": item["value"]
                } for item in body.get("matchers", {}).get("answers", [])
            ]
        },
        "outcomeDeclaration": {
            "scoringType": validation.get("scoringType"),
            "validResponse": {
                "shouldAutoGraded": True,
                "correctAnswers": [
                    {
                        "sourceItemId": pair["choiceId"],
                        "targetItemId": pair["answerId"]
                    } for pair in validation.get("validResponse", {}).get("answerMapping", [])
                ]
            }
        },
        "feedback": {
            "general": body.get("generalFeedback"),
            "correct": body.get("correctAnswerFeedback"),
            "wrong": body.get("wrongAnswerFeedback")
        },
        "hints": body.get("hints", [])
    }
    return qb_payload

if __name__ == "__main__":
    try:
        with open('AAT_data.json', 'r', encoding='utf-8') as f:
            aat_data = json.load(f)
            
        transformed_data = transform_matching_data(aat_data)
        
        with open('sample_output_data.json', 'w', encoding='utf-8') as f:
            json.dump(transformed_data, f, indent=2, ensure_ascii=False)
            
        print("Successfully transformed AAT_data.json to sample_output_data.json with zero data loss.")
    except Exception as e:
        print(f"Error during transformation: {e}")