def build_annotation_tags(raw):

    tags = raw.get("tags", {}) or {}

    tags["migration:source"] = "AAT"

    if raw.get("createdAt"):

        tags["migration:originalCreatedAt"] = (
            raw.get("createdAt")
        )

    authored = (
        raw.get("metadata", {})
        .get("authoredDate")
    )

    if authored:

        tags["migration:authoredDate"] = (
            authored
        )

    return tags