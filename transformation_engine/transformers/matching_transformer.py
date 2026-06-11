from helpers.mathml_converter import process_html_and_convert_math


class MatchingTransformer:

    def __init__(self, raw):
        self.raw = raw

    def transform(self):
        q = self.raw.get("response", self.raw)
        body = q.get("body") or {}
        validation = q.get("validation") or {}
        metadata_source = q.get("metadata") or {}

        created_user = q.get("createdByUser") or {}
        source_val = (
            created_user.get("name")
            or created_user.get("email")
            or metadata_source.get("author")
        )

        outcomes = metadata_source.get("curriculumOutcomes", [])
        first_outcome = outcomes[0] if outcomes else {}
        grade = first_outcome.get("grade", "")
        subject = first_outcome.get("subject", "")
        curriculum = first_outcome.get("curriculum", "")

        qb_payload = {
            "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
            "type": "MATCHING",
            "subType": "MATCHING_PAIRS",
            "metadata": {
                "general": {
                    "code": q.get("code"),
                    "externalId": q.get("id"),
                    "title": None,
                    "language": q.get("language", "EN_US"),
                    "keywords": metadata_source.get("keywords", []),
                    "parentReference": None,
                    "source": source_val,
                },
                "lifecycle": {
                    "status": q.get("status", "DRAFT"),
                },
                "technical": {
                    "penAndPaper": metadata_source.get("penAndPaper", False),
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
                    "logitValue": metadata_source.get("logitValue"),
                },
                "rights": {
                    "copyrights": metadata_source.get("copyrights", []),
                    "conditionsOfUse": metadata_source.get("conditionsOfUse", []),
                },
                "classification": {
                    "grade": grade,
                    "subject": subject,
                    "curriculum": curriculum,
                    "curriculumOutcomes": outcomes,
                    "subDomain": metadata_source.get("domains", []) or [],
                },
                "annotation": {
                    "tags": {
                        "migration:source": "AAT",
                        "migration:originalCreatedAt": q.get("createdAt"),
                        "migration:authoredDate": metadata_source.get("authoredDate"),
                    }
                },
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
                "sentence": None,
                "sourceItems": [
                    {
                        "id": item.get("id"),
                        "weight": item.get("weight", 1.0),
                        "content": {
                            "type": "text",
                            "text": process_html_and_convert_math(item.get("value", "")),
                        },
                        "feedback": (
                            process_html_and_convert_math(item.get("feedback", ""))
                            if item.get("feedback")
                            else None
                        ),
                    }
                    for item in body.get("matchers", {}).get("choices", [])
                ],
                "targetItems": [
                    {
                        "id": item.get("id"),
                        "content": {
                            "type": "text",
                            "text": process_html_and_convert_math(item.get("value", "")),
                        },
                    }
                    for item in body.get("matchers", {}).get("answers", [])
                ],
            },
            "responseDeclaration": {
                "type": "PAIR_MATCH",
                "cardinality": "MULTIPLE",
                "maxAttempts": 1,
            },
            "outcomeDeclaration": {
                "scoringType": validation.get("scoringType", "EXACT_MATCH"),
                "scoring": {
                    "normalizedMin": 0,
                    "normalizedMax": 1,
                    "defaultNormalizedValue": 0,
                },
                "maxScore": q.get("maxScore", 1),
            },
        }

        if body.get("prompt"):
            qb_payload["itemBody"]["statement"] = {
                "content": [
                    {
                        "type": "text",
                        "text": process_html_and_convert_math(body.get("prompt")),
                    }
                ]
            }

        feedback_block = {}
        if body.get("correctAnswerFeedback"):
            feedback_block["correct"] = {
                "content": [
                    {
                        "type": "text",
                        "text": process_html_and_convert_math(body.get("correctAnswerFeedback")),
                    }
                ]
            }
        if body.get("wrongAnswerFeedback"):
            feedback_block["incorrect"] = {
                "content": [
                    {
                        "type": "text",
                        "text": process_html_and_convert_math(body.get("wrongAnswerFeedback")),
                    }
                ]
            }
        if body.get("partialAnswerFeedback"):
            feedback_block["partial"] = {
                "content": [
                    {
                        "type": "text",
                        "text": process_html_and_convert_math(body.get("partialAnswerFeedback")),
                    }
                ]
            }
        if feedback_block:
            qb_payload["outcomeDeclaration"]["feedback"] = feedback_block

        if body.get("generalFeedback"):
            qb_payload["outcomeDeclaration"]["seeWhy"] = {
                "layout": "TEXT",
                "content": [
                    {
                        "type": "text",
                        "text": process_html_and_convert_math(body.get("generalFeedback")),
                    }
                ],
                "audio": None,
            }

        valid_resp = validation.get("validResponse")
        if valid_resp and valid_resp.get("answerMapping"):
            qb_payload["outcomeDeclaration"]["validResponse"] = {
                "shouldAutoGraded": True,
                "correctAnswers": [
                    {
                        "sourceItemId": pair.get("choiceId"),
                        "targetItemId": pair.get("answerId"),
                    }
                    for pair in valid_resp.get("answerMapping", [])
                ],
            }

        hints = body.get("hints", [])
        if hints:
            qb_payload["modalFeedback"] = {
                "needHelp": {
                    "content": {
                        "layout": "TEXT",
                        "content": [
                            {
                                "type": "text",
                                "text": process_html_and_convert_math(hint),
                            }
                            for hint in hints
                        ],
                    }
                },
                "passageId": None,
            }

        return qb_payload
