from helpers.annotation_mapper import (
    build_annotation_tags
)
from helpers.language_mapper import (
    languageMapper
)
def _normalize_curriculum_outcomes(outcomes):
    """Every CurriculumOutcome field (type/id/name/description/curriculum/
    grade/subject) is a required, non-null string per schema, but legacy
    source data sometimes leaves individual outcome entries blank. Backfill
    each blank field from the first outcome that does have it, so a gap in
    one entry doesn't reject the whole record.
    """
    required_fields = ("type", "id", "name", "description", "curriculum", "grade", "subject")

    fallback = {
        field: next(
            (o.get(field) for o in outcomes if o.get(field)),
            ""
        )
        for field in required_fields
    }

    normalized = []
    for outcome in outcomes:
        item = dict(outcome)
        for field in required_fields:
            if not item.get(field):
                item[field] = fallback[field]
        normalized.append(item)

    return normalized


def build_metadata(raw):

    metadata = raw.get("metadata", {})

    outcomes = _normalize_curriculum_outcomes(
        metadata.get(
            "curriculumOutcomes",
            []
        )
    )

    first = outcomes[0] if outcomes else {}

    return {

        "general": {

            "code": raw.get("code"),

            "externalId": raw.get("id"),

            "title": None,

            "language": languageMapper(raw.get("language")),

            "keywords":
                build_keywords(metadata),

            "parentReference": None,

            "source":"AAT"
        },

        "lifecycle": {
            "status": "DRAFT"
        },

        "technical": {
            "penAndPaper":
                metadata.get(
                    "penAndPaper",
                    False
                )
        },

        "educational": {

            "resourceType":
                metadata.get("resourceType"),

            "difficultyLevel":
                metadata.get(
                    "difficultyLevel"
                ),

            "cognitiveDimensions":
                metadata.get(
                    "cognitiveDimensions",
                    []
                ),

            "knowledgeDimensions":
                metadata.get(
                    "knowledgeDimensions",
                    []
                ),

            "summativeAssessment":
                metadata.get(
                    "summativeAssessment",
                    False
                ),

            "cefrLevel":
                metadata.get("cefrLevel"),

            "proficiency":
                metadata.get("proficiency"),

            "lexileLevel":
                metadata.get("lexileLevel"),

            "logitValue":
                metadata.get("logitValue")
        },

        "rights": {
            "copyrights":
                metadata.get(
                    "copyrights",
                    []
                )
        },

        "classification": {

            "grade":
                first.get("grade"),

            "subject":
                first.get("subject"),

            "curriculum":
                first.get("curriculum") ,

            "curriculumOutcomes":
                outcomes,

            "subDomain":
                build_subdomain(metadata) or None
        },

        "annotation": {
            "tags":
                build_annotation_tags(raw) or {}
        }
    }


def build_keywords(metadata):

    keywords = metadata.get(
        "keywords",
        []
    )

    skill_id = metadata.get("skillId")

    sub_skill = metadata.get("subSkill")

    if skill_id:
        keywords.append(
            f"skillId:{skill_id}"
        )

    if sub_skill:
        keywords.append(
            f"subSkill:{sub_skill}"
        )

    return keywords


def build_subdomain(metadata):

    domains = metadata.get(
        "domains",
        []
    ) or []

    sub_skill = metadata.get(
        "subSkill"
    )

    if sub_skill:
        domains.append(sub_skill)

    return domains