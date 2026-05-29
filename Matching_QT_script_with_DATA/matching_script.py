import json

def transform_matching_data(aat_data):
    response = aat_data.get("response", {})
    body = response.get("body", {})
    validation = response.get("validation", {})
    metadata_source = response.get("metadata", {})

    created_user = response.get("createdByUser") or {}
    source_val = created_user.get("name") or created_user.get("email") or metadata_source.get("author")

    outcomes = metadata_source.get("curriculumOutcomes", [])
    grade = outcomes[0].get("grade", "") if outcomes else ""
    subject = outcomes[0].get("subject", "") if outcomes else ""
    curriculum = outcomes[0].get("curriculum", "") if outcomes else ""

    qb_payload = {
        "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
        "type": "MATCHING",
        "subType": "MATCHING_PAIRS",
        "metadata": {
            "general": {
                "code": response.get("code"),
                "externalId": response.get("id"),
                "title": None,
                "language": response.get("language", "EN_US"),
                "keywords": metadata_source.get("keywords", []),
                "parentReference": None,
                "source": source_val
            },
            "lifecycle": {
                "status": response.get("status", "DRAFT")
            },
            "technical": {
                "penAndPaper": metadata_source.get("penAndPaper", False)
            },
            "educational": {
                "resourceType": metadata_source.get("resourceType"),
                "difficultyLevel": metadata_source.get("difficultyLevel"),
                "cognitiveDimensions": metadata_source.get("cognitiveDimensions", []),
                "knowledgeDimensions": metadata_source.get("knowledgeDimensions", []),
                "summativeAssessment": metadata_source.get("summativeAssessment", False),
                "cefrLevel": metadata_source.get("cefrLevel"),
                "proficiency": metadata_source.get("proficiency"),
                "lexileLevel": metadata_source.get("lexileLevel"),
                "logitValue": metadata_source.get("logitValue")
            },
            "rights": {
                "copyrights": metadata_source.get("copyrights", []),
                "conditionsOfUse": metadata_source.get("conditionsOfUse", [])
            },
            "classification": {
                "grade": grade,
                "subject": subject,
                "curriculum": curriculum,
                "curriculumOutcomes": outcomes,
                "subDomain": metadata_source.get("domains", []) or []
            },
            "annotation": {
                "tags": {
                    "migration:source": "AAT",
                    "migration:originalCreatedAt": response.get("createdAt"),
                    "migration:authoredDate": metadata_source.get("authoredDate")
                }
            }
        },
        "itemBody": {
            "version": "1.0",
            "title": None,
            "subTitle": None,
            "instruction": None,
            "audio": None,
            "video": None,
            "backgroundLayout": None,
            "timeSpentConfig": None,
            "splitContent": None,
            "sideImage": None,
            "shuffled": body.get("matchers", {}).get("shuffle", True),
            "statement": None, 
            "sentence": None, # [ADDED] Global schema requirement from TL
            "sourceItems": [
                {
                    "id": item["id"],
                    "weight": item.get("weight", 1.0),
                    # [UPDATED] Wrapped text in content object
                    "content": {
                        "type": "text",
                        "text": item.get("value", "")
                    },
                    "feedback": item.get("feedback")
                } for item in body.get("matchers", {}).get("choices", [])
            ],
            "targetItems": [
                {
                    "id": item["id"],
                    # [UPDATED] Wrapped text in content object
                    "content": {
                        "type": "text",
                        "text": item.get("value", "")
                    }
                } for item in body.get("matchers", {}).get("answers", [])
            ]
        },
        "responseDeclaration": {
            "type": "PAIR_MATCH",
            "cardinality": "MULTIPLE",
            "maxAttempts": 1
        },
        "outcomeDeclaration": {
            "scoringType": validation.get("scoringType", "EXACT_MATCH"),
            "scoring": {
                "normalizedMin": 0,
                "normalizedMax": 1,
                "defaultNormalizedValue": 0
            },
            "maxScore": response.get("maxScore", 1)
        }
    }

    if body.get("prompt"):
        qb_payload["itemBody"]["statement"] = {
            "content": [{"type": "text", "text": body.get("prompt")}]
        }

    feedback_block = {}
    if body.get("correctAnswerFeedback"):
        feedback_block["correct"] = {"content": [{"type": "text", "text": body.get("correctAnswerFeedback")}]}
    if body.get("wrongAnswerFeedback"):
        feedback_block["incorrect"] = {"content": [{"type": "text", "text": body.get("wrongAnswerFeedback")}]}
    if body.get("partialAnswerFeedback"):
        feedback_block["partial"] = {"content": [{"type": "text", "text": body.get("partialAnswerFeedback")}]}
    
    if feedback_block:
        qb_payload["outcomeDeclaration"]["feedback"] = feedback_block

    if body.get("generalFeedback"):
        qb_payload["outcomeDeclaration"]["seeWhy"] = {
            "layout": "TEXT",
            "content": [{"type": "text", "text": body.get("generalFeedback")}],
            "audio": None
        }

    valid_resp = validation.get("validResponse")
    if valid_resp and valid_resp.get("answerMapping"):
        qb_payload["outcomeDeclaration"]["validResponse"] = {
            "shouldAutoGraded": True,
            "correctAnswers": [
                {
                    "sourceItemId": pair.get("choiceId"),
                    "targetItemId": pair.get("answerId")
                } for pair in valid_resp.get("answerMapping", [])
            ]
        }

    hints = body.get("hints", [])
    if hints:
        qb_payload["modalFeedback"] = {
            "needHelp": {
                "content": {
                    "layout": "TEXT",
                    "content": [{"type": "text", "text": hint} for hint in hints]
                }
            },
            "passageId": None
        }

    return qb_payload

if __name__ == "__main__":
    try:
        with open('AAT_data.json', 'r', encoding='utf-8') as f:
            aat_data = json.load(f)
            
        transformed_data = transform_matching_data(aat_data)
        
        with open('sample_output_data.json', 'w', encoding='utf-8') as f:
            json.dump(transformed_data, f, indent=2, ensure_ascii=False)
            
        print("Successfully applied TL's schema updates (sentence & content wrapper).")
    except Exception as e:
        print(f"Error during transformation: {e}")