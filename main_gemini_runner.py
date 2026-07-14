import os
import json
import re
import time
import traceback
import threading
from collections import deque
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError, ServerError

from services.gemini_usage_reporter import GeminiUsageReporter
from services.curriculum_file_resolver import (
    resolve_curriculum_files_for_record,
    get_curriculum_files_for_contents,
    get_curriculum_file_references_for_report
)
from services.lesson_context_resolver import (
    build_lesson_context_text,
    get_record_lo_id,
    load_lesson_context
)
from services.response_validator import (
    assess_gemini_response
)
from services.batch_classification import (
    _record_estimated_text_tokens as estimate_batch_record_text_tokens,
    add_usage,
    build_batch_instruction,
    build_batches,
    build_content_manifest,
    build_question_text,
    distribute_usage,
    empty_usage,
    get_record_question_id as get_batch_question_id,
    get_record_subject as get_batch_subject,
    load_allowed_outcome_keys,
    reconcile_batch_response
)
from services.prompt_builder import (
    build_prompt as build_single_prompt
)


load_dotenv()


def read_int_env(
    name,
    default
):
    try:
        return int(
            os.getenv(
                name,
                str(default)
            )
        )

    except Exception:
        return default


def read_optional_int_env(
    name,
    default=None
):
    value = os.getenv(
        name
    )

    if value is None:
        return default

    value = str(
        value
    ).strip()

    if not value or value.lower() == "none":
        return None

    try:
        return int(
            value
        )

    except Exception:
        return default


def read_bool_env(
    name,
    default
):
    value = str(
        os.getenv(
            name,
            str(default)
        )
    ).strip().lower()

    return value in {
        "1",
        "true",
        "yes",
        "y",
        "on"
    }


def read_float_env(
    name,
    default
):
    try:
        return float(
            os.getenv(
                name,
                str(default)
            )
        )

    except Exception:
        return default


def read_list_env(
    name,
    default
):
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return list(default)

    values = [
        item.strip()
        for item in str(raw_value).split(",")
        if item.strip()
    ]

    return values or list(default)


def sanitize_model_env_key(
    model_name
):
    return re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        str(model_name or "").strip()
    ).strip("_").upper()


DEFAULT_MODEL_PRICING = {
    "GEMINI_2_5_FLASH_LITE": {
        "input_per_million_tokens": 0.10,
        "output_per_million_tokens": 0.40,
        "cache_per_million_tokens": 0.01
    },
    "GEMINI_2_5_FLASH": {
        "input_per_million_tokens": 0.30,
        "output_per_million_tokens": 2.50,
        "cache_per_million_tokens": 0.03
    }
}


def get_model_pricing(
    model_name
):
    model_key = sanitize_model_env_key(
        model_name
    )
    defaults = DEFAULT_MODEL_PRICING.get(
        model_key,
        {}
    )

    return {
        "input_per_million_tokens": read_float_env(
            f"AI_ENGINE_PRICE_{model_key}_INPUT_PER_MTOKENS",
            defaults.get("input_per_million_tokens", 0.0)
        ),
        "output_per_million_tokens": read_float_env(
            f"AI_ENGINE_PRICE_{model_key}_OUTPUT_PER_MTOKENS",
            defaults.get("output_per_million_tokens", 0.0)
        ),
        "cache_per_million_tokens": read_float_env(
            f"AI_ENGINE_PRICE_{model_key}_CACHE_PER_MTOKENS",
            defaults.get("cache_per_million_tokens", 0.0)
        )
    }


def tokens_to_cost(
    token_count,
    price_per_million_tokens
):
    return (
        float(token_count or 0)
        /
        1_000_000.0
    ) * float(price_per_million_tokens or 0.0)


def build_billing_summary(
    summary,
    final_execution_report
):
    by_model = {}
    total_input_cost = 0.0
    total_output_cost = 0.0
    total_cache_cost = 0.0
    unpriced_models = []

    for model_name, item in (
        final_execution_report.get("by_model", {})
        or {}
    ).items():
        pricing = get_model_pricing(
            model_name
        )
        estimated_prompt_tokens = int(
            item.get("estimated_prompt_tokens") or 0
        )
        actual_input_tokens = int(
            item.get("prompt_tokens") or 0
        )
        output_tokens = int(
            item.get("output_tokens") or 0
        )
        thinking_tokens = int(
            item.get("thinking_tokens") or 0
        )
        cached_tokens = int(
            item.get("cached_tokens") or 0
        )
        billable_output_tokens = (
            output_tokens + thinking_tokens
        )

        input_cost = tokens_to_cost(
            actual_input_tokens,
            pricing["input_per_million_tokens"]
        )
        output_cost = tokens_to_cost(
            billable_output_tokens,
            pricing["output_per_million_tokens"]
        )
        cache_cost = tokens_to_cost(
            cached_tokens,
            pricing["cache_per_million_tokens"]
        )

        if (
            actual_input_tokens
            or billable_output_tokens
            or cached_tokens
        ) and not any(
            pricing.values()
        ):
            unpriced_models.append(
                model_name
            )

        total_input_cost += input_cost
        total_output_cost += output_cost
        total_cache_cost += cache_cost

        by_model[model_name] = {
            "records": int(item.get("records") or 0),
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "actual_input_tokens": actual_input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "billable_output_tokens": billable_output_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": int(item.get("total_tokens") or 0),
            "pricing": pricing,
            "estimated_billing_usd": round(
                input_cost + output_cost + cache_cost,
                6
            ),
            "billing_breakdown_usd": {
                "input": round(input_cost, 6),
                "output_including_thinking": round(output_cost, 6),
                "cache": round(cache_cost, 6)
            }
        }

    total_expected_billing = (
        total_input_cost
        +
        total_output_cost
        +
        total_cache_cost
    )

    return {
        "estimated_prompt_tokens": int(
            summary.get("estimated_prompt_tokens") or 0
        ),
        "actual_input_tokens": int(
            summary.get("actual_prompt_tokens") or 0
        ),
        "output_tokens": int(
            summary.get("output_tokens") or 0
        ),
        "thinking_tokens": int(
            summary.get("thinking_tokens") or 0
        ),
        "billable_output_tokens": int(
            (summary.get("output_tokens") or 0)
            +
            (summary.get("thinking_tokens") or 0)
        ),
        "cached_tokens": int(
            summary.get("cached_tokens") or 0
        ),
        "total_tokens": int(
            summary.get("total_tokens") or 0
        ),
        "expected_billing_usd": round(
            total_expected_billing,
            6
        ),
        "billing_breakdown_usd": {
            "input": round(total_input_cost, 6),
            "output_including_thinking": round(total_output_cost, 6),
            "cache": round(total_cache_cost, 6)
        },
        "by_model": by_model,
        "unpriced_models": sorted(
            set(unpriced_models)
        )
    }


def print_billing_summary(
    billing_summary
):
    print(
        "\n========== TOKEN & BILLING ==========",
        flush=True
    )
    print(
        f"Estimated Prompt Tokens : {billing_summary.get('estimated_prompt_tokens')}",
        flush=True
    )
    print(
        f"Actual Input Tokens     : {billing_summary.get('actual_input_tokens')}",
        flush=True
    )
    print(
        f"Output Tokens           : {billing_summary.get('output_tokens')}",
        flush=True
    )
    print(
        f"Thinking Tokens         : {billing_summary.get('thinking_tokens')}",
        flush=True
    )
    print(
        f"Billable Output Tokens  : {billing_summary.get('billable_output_tokens')}",
        flush=True
    )
    print(
        f"Cached Tokens           : {billing_summary.get('cached_tokens')}",
        flush=True
    )
    print(
        f"Total Tokens            : {billing_summary.get('total_tokens')}",
        flush=True
    )
    print(
        f"Expected Billing (USD)  : ${billing_summary.get('expected_billing_usd'):.6f}",
        flush=True
    )

    by_model = billing_summary.get(
        "by_model",
        {}
    ) or {}

    if by_model:
        print(
            "By Model:",
            flush=True
        )

        for model_name, item in by_model.items():
            print(
                f"{model_name}: input={item.get('actual_input_tokens')} "
                f"output={item.get('output_tokens')} "
                f"thinking={item.get('thinking_tokens')} "
                f"cached={item.get('cached_tokens')} "
                f"bill=${item.get('estimated_billing_usd'):.6f}",
                flush=True
            )

    if billing_summary.get(
        "unpriced_models"
    ):
        print(
            "Unpriced Models         : "
            + ", ".join(
                billing_summary["unpriced_models"]
            ),
            flush=True
        )


def print_pre_run_billing_estimate(
    estimate
):
    print(
        "\n========== PRE-RUN BILLING ESTIMATE ==========",
        flush=True
    )
    print(
        f"Estimated Prompt Tokens : {estimate.get('estimated_prompt_tokens')}",
        flush=True
    )
    print(
        f"Estimate Mode           : {estimate.get('estimate_mode')}",
        flush=True
    )
    print(
        f"Expected Billing (USD)  : ${estimate.get('expected_billing_usd'):.6f}",
        flush=True
    )

    by_model = estimate.get(
        "by_model",
        {}
    ) or {}

    if by_model:
        print(
            "By Model:",
            flush=True
        )

        for model_name, item in by_model.items():
            print(
                f"{model_name}: prompt_est={item.get('estimated_prompt_tokens')} "
                f"bill=${item.get('estimated_billing_usd'):.6f}",
                flush=True
            )

    token_count_errors = estimate.get(
        "token_count_errors"
    ) or []

    if token_count_errors:
        print(
            f"Token Count Errors      : {len(token_count_errors)}",
            flush=True
        )


def estimate_text_tokens_locally(
    value
):
    text = str(
        value or ""
    )

    if not text:
        return 0

    return max(
        1,
        (len(text) + 3) // 4
    )


def count_resolved_images_for_estimate(
    record
):
    return sum(
        1
        for image in get_record_images(record)
        if isinstance(image, dict)
        and image.get("exists") is True
        and image.get("local_path")
    )


def estimate_batch_prompt_tokens_locally(
    batch,
    subject
):
    records = batch.get(
        "records",
        []
    )
    question_ids = [
        get_batch_question_id(record)
        for record in records
    ]
    first_record = records[0] if records else {}
    lesson_context_text = build_lesson_context_text(
        load_lesson_context(
            get_record_lo_id(first_record)
        )
    )
    instruction_text = build_batch_instruction(
        subject,
        question_ids,
        grade=first_record.get("grade")
    )
    image_count = sum(
        count_resolved_images_for_estimate(record)
        for record in records
    )
    curriculum_file_count = len(
        batch.get("group_key", [None, None, None, None, ()])[4]
        or []
    )

    return {
        "estimated_prompt_tokens": (
            int(batch.get("estimated_text_tokens") or 0)
            +
            estimate_text_tokens_locally(instruction_text)
            +
            estimate_text_tokens_locally(lesson_context_text)
            +
            image_count * PREFLIGHT_IMAGE_TOKEN_ESTIMATE
            +
            curriculum_file_count * PREFLIGHT_CURRICULUM_FILE_TOKEN_ESTIMATE
        ),
        "image_count": image_count,
        "curriculum_file_count": curriculum_file_count,
        "lesson_context_attached": bool(lesson_context_text),
        "lesson_context_char_count": len(lesson_context_text)
    }


def build_batch_metadata_for_records(
    records,
    curriculum_file_keys=(),
    missing_curriculum_file_keys=()
):
    return {
        "records": records,
        "estimated_text_tokens": sum(
            estimate_batch_record_text_tokens(record)
            for record in records
        ),
        "image_count": sum(
            count_resolved_images_for_estimate(record)
            for record in records
        ),
        "group_key": (
            None,
            None,
            None,
            None,
            tuple(curriculum_file_keys or ()),
            tuple(missing_curriculum_file_keys or ())
        )
    }


def estimate_single_prompt_tokens_locally(
    record,
    prompt
):
    lesson_context_text = build_lesson_context_text(
        load_lesson_context(
            get_record_lo_id(record)
        )
    )
    image_count = count_resolved_images_for_estimate(
        record
    )

    return {
        "estimated_prompt_tokens": (
            estimate_text_tokens_locally(prompt)
            +
            estimate_text_tokens_locally(lesson_context_text)
            +
            image_count * PREFLIGHT_IMAGE_TOKEN_ESTIMATE
        ),
        "image_count": image_count,
        "curriculum_file_count": 0,
        "lesson_context_attached": bool(lesson_context_text),
        "lesson_context_char_count": len(lesson_context_text)
    }


def build_pre_run_billing_estimate(
    reporter,
    client,
    uploaded_files,
    valid_records,
    runnable_batches
):
    estimate_rows = []
    by_model = {}
    total_estimated_prompt_tokens = 0
    total_expected_billing = 0.0
    token_count_errors = []
    estimate_mode = (
        PREFLIGHT_BILLING_MODE
        if PREFLIGHT_BILLING_MODE in {"exact", "local_estimate"}
        else "local_estimate"
    )
    use_exact_count = estimate_mode == "exact"

    if not client and use_exact_count:
        estimate = {
            "enabled": False,
            "reason": "client_unavailable",
            "estimate_mode": estimate_mode,
            "generated_at": datetime.now().isoformat(),
            "request_count": 0,
            "estimated_prompt_tokens": 0,
            "expected_billing_usd": 0.0,
            "by_model": {},
            "token_count_errors": [],
            "rows": []
        }
        reporter.write_json(
            reporter.report_root / "pre_run_billing_estimate.json",
            estimate
        )
        return estimate

    if BATCH_ENABLED:
        work_items = list(
            runnable_batches
        )
    else:
        work_items = list(
            valid_records
        )

    for item in work_items:
        if BATCH_ENABLED:
            batch_number, batch = item
            batch_id = f"batch_{batch_number:06d}"
            records = batch.get(
                "records",
                []
            )

            if not records:
                continue

            first_record = records[0]
            subject = get_batch_subject(
                first_record
            )
            model_name = build_models_to_try()[0]

            if use_exact_count:
                local_detail = estimate_batch_prompt_tokens_locally(
                    batch=batch,
                    subject=subject
                )
                curriculum_result = resolve_curriculum_files_for_record(
                    client=client,
                    record=first_record,
                    uploaded_files=uploaded_files,
                    min_grade=1,
                    max_grade=12
                )
                curriculum_files = get_curriculum_files_for_contents(
                    curriculum_result
                )
                contents, image_reports = build_batch_contents(
                    curriculum_files=curriculum_files,
                    records=records,
                    subject=subject
                )
                estimated_prompt_tokens, token_error = estimate_tokens_for_request(
                    client=client,
                    model_name=model_name,
                    contents=contents,
                    local_estimated_tokens=local_detail["estimated_prompt_tokens"],
                    question_id=batch_id
                )
                local_detail = {
                    "image_count": sum(
                        len(items)
                        for items in image_reports.values()
                    ),
                    "curriculum_file_count": len(curriculum_files),
                    "lesson_context_attached": None,
                    "lesson_context_char_count": None
                }
            else:
                local_detail = estimate_batch_prompt_tokens_locally(
                    batch=batch,
                    subject=subject
                )
                estimated_prompt_tokens = local_detail[
                    "estimated_prompt_tokens"
                ]
                token_error = None

            row = {
                "request_mode": "batch",
                "estimate_mode": estimate_mode,
                "batch_id": batch_id,
                "question_ids": [
                    get_batch_question_id(record)
                    for record in records
                ],
                "subject": subject,
                "batch_size": len(records),
                "model_name": model_name,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "token_count_error": token_error,
                "image_count": local_detail["image_count"],
                "curriculum_file_count": local_detail["curriculum_file_count"],
                "lesson_context_attached": local_detail[
                    "lesson_context_attached"
                ],
                "lesson_context_char_count": local_detail[
                    "lesson_context_char_count"
                ]
            }
        else:
            record = item
            question_id = get_record_question_id(
                record
            )
            subject = get_record_subject(
                record
            )
            prompt = get_record_prompt(
                record
            )
            local_detail = estimate_single_prompt_tokens_locally(
                record=record,
                prompt=prompt
            )
            model_name = build_models_to_try(
                prefer_fallback=should_start_with_fallback_model(
                    subject=subject,
                    prompt=prompt,
                    image_count=local_detail["image_count"]
                )
            )[0]

            if use_exact_count:
                curriculum_result = resolve_curriculum_files_for_record(
                    client=client,
                    record=record,
                    uploaded_files=uploaded_files,
                    min_grade=1,
                    max_grade=12
                )
                curriculum_files = get_curriculum_files_for_contents(
                    curriculum_result
                )
                lesson_context_text = build_lesson_context_text(
                    load_lesson_context(
                        get_record_lo_id(record)
                    )
                )
                pil_images, image_report = load_images_for_record(
                    record
                )
                contents = build_contents(
                    curriculum_files=curriculum_files,
                    pil_images=pil_images,
                    prompt=prompt,
                    lesson_context_text=lesson_context_text
                )
                estimated_prompt_tokens, token_error = estimate_tokens_for_request(
                    client=client,
                    model_name=model_name,
                    contents=contents,
                    local_estimated_tokens=local_detail["estimated_prompt_tokens"],
                    question_id=question_id
                )
                local_detail = {
                    "image_count": len(image_report),
                    "curriculum_file_count": len(curriculum_files),
                    "lesson_context_attached": bool(lesson_context_text),
                    "lesson_context_char_count": len(lesson_context_text)
                }
            else:
                estimated_prompt_tokens = local_detail[
                    "estimated_prompt_tokens"
                ]
                token_error = None

            row = {
                "request_mode": "single",
                "estimate_mode": estimate_mode,
                "question_id": question_id,
                "subject": subject,
                "model_name": model_name,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "token_count_error": token_error,
                "image_count": local_detail["image_count"],
                "curriculum_file_count": local_detail["curriculum_file_count"],
                "lesson_context_attached": local_detail[
                    "lesson_context_attached"
                ],
                "lesson_context_char_count": local_detail[
                    "lesson_context_char_count"
                ]
            }

        estimate_rows.append(
            row
        )

    for row in estimate_rows:
        model_name = str(
            row.get("model_name") or "UNKNOWN"
        )
        estimated_prompt_tokens = int(
            row.get("estimated_prompt_tokens") or 0
        )
        pricing = get_model_pricing(
            model_name
        )
        estimated_billing_usd = tokens_to_cost(
            estimated_prompt_tokens,
            pricing.get("input_per_million_tokens")
        )

        total_estimated_prompt_tokens += estimated_prompt_tokens
        total_expected_billing += estimated_billing_usd

        if model_name not in by_model:
            by_model[model_name] = {
                "calls": 0,
                "estimated_prompt_tokens": 0,
                "pricing": pricing,
                "estimated_billing_usd": 0.0
            }

        by_model[model_name]["calls"] += 1
        by_model[model_name]["estimated_prompt_tokens"] += (
            estimated_prompt_tokens
        )
        by_model[model_name]["estimated_billing_usd"] += (
            estimated_billing_usd
        )

        if row.get(
            "token_count_error"
        ):
            token_count_errors.append(
                row
            )

    for item in by_model.values():
        item["estimated_billing_usd"] = round(
            item["estimated_billing_usd"],
            6
        )

    estimate = {
        "enabled": True,
        "estimate_mode": estimate_mode,
        "generated_at": datetime.now().isoformat(),
        "request_count": len(estimate_rows),
        "estimated_prompt_tokens": total_estimated_prompt_tokens,
        "expected_billing_usd": round(
            total_expected_billing,
            6
        ),
        "by_model": by_model,
        "token_count_errors": token_count_errors,
        "rows": estimate_rows
    }

    reporter.write_json(
        reporter.report_root / "pre_run_billing_estimate.json",
        estimate
    )

    return estimate


def resolve_project_root():
    start_points = [
        Path.cwd().resolve(),
        Path(__file__).resolve().parent
    ]

    checked = set()

    for start in start_points:
        current = start

        while True:
            if current in checked:
                break

            checked.add(
                current
            )

            markers = [
                current / "config" / "course_code_mapping.json",
                current / "services",
                current / "prompts"
            ]

            if all(
                marker.exists()
                for marker in markers
            ):
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError(
        "Project root not found. Expected a folder containing "
        "config/course_code_mapping.json, services/, and prompts/."
    )


PROJECT_ROOT = resolve_project_root()

PROMPT_PREVIEW_ROOT = (
    PROJECT_ROOT
    /
    "output"
    /
    "prompt_preview_image_only"
)

UPLOADED_FILES_PATH = (
    PROJECT_ROOT
    /
    "cache"
    /
    "uploaded_files.json"
)

PROCESS_LIMIT = read_int_env(
    "AI_ENGINE_PROCESS_LIMIT",
    0
)

SKIP_PREVIOUS_SUCCESSES = read_bool_env(
    "AI_ENGINE_SKIP_PREVIOUS_SUCCESSES",
    True
)

SKIP_SUBJECTS = tuple(
    str(item).strip().upper()
    for item in read_list_env(
        "AI_ENGINE_SKIP_SUBJECTS",
        []
    )
    if str(item).strip()
)

MAX_WORKERS = read_int_env(
    
    "AI_ENGINE_MAX_WORKERS",
    1
)

PRIMARY_MODEL = os.getenv(
    "AI_ENGINE_PRIMARY_MODEL",
    "gemini-2.5-flash-lite"
).strip()

FALLBACK_MODELS = read_list_env(
    "AI_ENGINE_FALLBACK_MODELS",
    ["gemini-2.5-flash"]
)

MIN_CONFIDENCE = read_float_env(
    "AI_ENGINE_MIN_CONFIDENCE",
    0.8
)

FORCE_JSON_RESPONSE = read_bool_env(
    "AI_ENGINE_FORCE_JSON_RESPONSE",
    True
)

DIRECT_FLASH_IMAGE_THRESHOLD = read_int_env(
    "AI_ENGINE_DIRECT_FLASH_IMAGE_THRESHOLD",
    2
)

DIRECT_FLASH_COMPLEX_PROMPT_CHARS = read_int_env(
    "AI_ENGINE_DIRECT_FLASH_COMPLEX_PROMPT_CHARS",
    3500
)

MAX_RETRIES_PER_MODEL = 5

RETRY_BASE_SECONDS = 2

BATCH_ENABLED = read_bool_env(
    "AI_ENGINE_BATCH_ENABLED",
    True
)

BATCH_PREVIEW_ONLY = read_bool_env(
    "AI_ENGINE_BATCH_PREVIEW_ONLY",
    False
)

PREFLIGHT_BILLING_ENABLED = read_bool_env(
    "AI_ENGINE_PREFLIGHT_BILLING_ENABLED",
    True
)

PREFLIGHT_BILLING_MODE = str(
    os.getenv(
        "AI_ENGINE_PREFLIGHT_BILLING_MODE",
        "local_estimate"
    )
).strip().lower()

USE_REMOTE_TOKEN_COUNT = read_bool_env(
    "AI_ENGINE_USE_REMOTE_TOKEN_COUNT",
    True
)

PREFLIGHT_IMAGE_TOKEN_ESTIMATE = read_int_env(
    "AI_ENGINE_PREFLIGHT_IMAGE_TOKEN_ESTIMATE",
    258
)

PREFLIGHT_CURRICULUM_FILE_TOKEN_ESTIMATE = read_int_env(
    "AI_ENGINE_PREFLIGHT_CURRICULUM_FILE_TOKEN_ESTIMATE",
    0
)

TRIAL_TOKENS_PER_MINUTE = read_optional_int_env(
    "AI_ENGINE_TRIAL_TOKENS_PER_MINUTE",
    None
)

BATCH_MAX_QUESTIONS = read_int_env(
    "AI_ENGINE_BATCH_MAX_QUESTIONS",
    10
)

BATCH_MAX_IMAGES = read_int_env(
    "AI_ENGINE_BATCH_MAX_IMAGES",
    20
)

BATCH_MAX_ESTIMATED_TEXT_TOKENS = read_int_env(
    "AI_ENGINE_BATCH_MAX_ESTIMATED_TEXT_TOKENS",
    20000
)

BATCH_MAX_INPUT_TOKENS = read_int_env(
    "AI_ENGINE_BATCH_MAX_INPUT_TOKENS",
    60000
)

BATCH_INVALID_JSON_RETRIES = read_int_env(
    "AI_ENGINE_BATCH_INVALID_JSON_RETRIES",
    1
)

ASSEMBLED_REQUEST_PREVIEW_LIMIT = read_int_env(
    "AI_ENGINE_ASSEMBLED_REQUEST_PREVIEW_LIMIT",
    20
)

TRIAL_API_LIMIT_PER_MINUTE = read_int_env(
    "AI_ENGINE_TRIAL_API_LIMIT_PER_MINUTE",
    5
)

TRIAL_API_LIMIT_PER_DAY = read_optional_int_env(
    "AI_ENGINE_TRIAL_API_LIMIT_PER_DAY",
    20
)

FAIL_SCHEMA_VALIDATION = (
    str(
        os.getenv(
            "AI_ENGINE_FAIL_SCHEMA_VALIDATION",
            "false"
        )
    )
    .strip()
    .lower()
    in {"1", "true", "yes", "y"}
)


OUTCOME_KEY_CACHE = {}
OUTCOME_KEY_CACHE_LOCK = threading.Lock()
RUN_STATE = {
    "progress": None,
    "reporter": None,
    "stop_requested": False,
    "stop_reason": None
}


class ApiRateLimiter:
    def __init__(
        self,
        limit_per_minute,
        limit_per_day=None
    ):
        self.limit_per_minute = max(
            1,
            int(limit_per_minute or 1)
        )
        normalized_day_limit = (
            int(limit_per_day)
            if limit_per_day is not None
            else None
        )
        self.limit_per_day = (
            normalized_day_limit
            if normalized_day_limit is not None
            and normalized_day_limit > 0
            else None
        )
        self.lock = threading.Lock()
        self.minute_timestamps = deque()
        self.day_timestamps = deque()

    def acquire(
        self
    ):
        waited = 0

        while True:
            with self.lock:
                if (
                    self.limit_per_day is not None
                    and len(self.day_timestamps) >= self.limit_per_day
                ):
                    raise ApiCallLimitReached(
                        limit_scope="day",
                        limit_value=self.limit_per_day
                    )

                now = time.time()
                minute_cutoff = now - 60
                day_cutoff = now - 86400

                while (
                    self.minute_timestamps
                    and self.minute_timestamps[0] <= minute_cutoff
                ):
                    self.minute_timestamps.popleft()

                while (
                    self.day_timestamps
                    and self.day_timestamps[0] <= day_cutoff
                ):
                    self.day_timestamps.popleft()

                if len(self.minute_timestamps) < self.limit_per_minute:
                    self.minute_timestamps.append(now)
                    self.day_timestamps.append(now)
                    return waited

                wait_time = max(
                    0,
                    60 - (now - self.minute_timestamps[0])
                )

            if wait_time > 0:
                time.sleep(wait_time)
                waited += wait_time


class TokenRateLimiter:
    def __init__(
        self,
        limit_per_minute=None
    ):
        self.limit_per_minute = (
            int(limit_per_minute)
            if limit_per_minute is not None
            else None
        )
        self.lock = threading.Lock()
        self.minute_events = deque()
        self.minute_total = 0

    def acquire(
        self,
        token_count
    ):
        token_count = max(
            0,
            int(token_count or 0)
        )

        if not self.limit_per_minute or token_count <= 0:
            return 0

        if token_count > self.limit_per_minute:
            raise ApiCallLimitReached(
                limit_scope="token_minute",
                limit_value=self.limit_per_minute
            )

        waited = 0

        while True:
            with self.lock:
                now = time.time()
                minute_cutoff = now - 60

                while (
                    self.minute_events
                    and self.minute_events[0][0] <= minute_cutoff
                ):
                    _, expired_tokens = self.minute_events.popleft()
                    self.minute_total -= expired_tokens

                if self.minute_total + token_count <= self.limit_per_minute:
                    self.minute_events.append(
                        (now, token_count)
                    )
                    self.minute_total += token_count
                    return waited

                deficit = (
                    self.minute_total
                    + token_count
                    - self.limit_per_minute
                )
                wait_time = 0

                running_total = self.minute_total
                for event_time, event_tokens in self.minute_events:
                    running_total -= event_tokens
                    if running_total + token_count <= self.limit_per_minute:
                        wait_time = max(
                            0,
                            60 - (now - event_time)
                        )
                        break

            if wait_time <= 0:
                wait_time = 1

            time.sleep(
                wait_time
            )
            waited += wait_time


class ApiCallLimitReached(Exception):
    def __init__(
        self,
        limit_scope,
        limit_value
    ):
        super().__init__(
            f"Gemini API {limit_scope} limit reached: {limit_value}"
        )
        self.limit_scope = limit_scope
        self.limit_value = limit_value


API_RATE_LIMITER = ApiRateLimiter(
    TRIAL_API_LIMIT_PER_MINUTE,
    limit_per_day=TRIAL_API_LIMIT_PER_DAY
)

TOKEN_RATE_LIMITER = TokenRateLimiter(
    TRIAL_TOKENS_PER_MINUTE
)


def acquire_api_slot(
    progress,
    api_name,
    question_id=None,
    model_name=None,
    estimated_token_count=None
):
    wait_time = API_RATE_LIMITER.acquire()
    token_wait_time = TOKEN_RATE_LIMITER.acquire(
        estimated_token_count
    )
    wait_time = max(
        wait_time,
        token_wait_time
    )

    if wait_time > 0 and progress:
        progress._print(
            f"[API RATE LIMIT] API={api_name} | "
            f"QID={question_id} | "
            f"Model={model_name} | "
            f"Waiting={round(wait_time, 2)}s"
        )

    return wait_time


def is_quota_error(
    error
):
    if not error:
        return False

    error_text = " ".join(
        [
            str(error),
            type(error).__name__
        ]
    ).lower()

    quota_markers = [
        "resource_exhausted",
        "quota",
        "rate limit",
        "ratelimit",
        "too many requests",
        "429",
        "limit exceeded"
    ]

    return any(
        marker in error_text
        for marker in quota_markers
    )


def summarize_error_reason(
    error_payload
):
    if not isinstance(
        error_payload,
        dict
    ):
        return str(
            error_payload
        )

    message = error_payload.get(
        "error_message"
    ) or error_payload.get(
        "error_type"
    ) or "Unknown error"

    if error_payload.get(
        "quota_exceeded"
    ):
        return f"Quota exceeded: {message}"

    return message


class ProgressPrinter:
    def __init__(
        self,
        total_records
    ):
        self.total_records = total_records

        self.lock = threading.Lock()

        self.api_calls_started = 0
        self.api_calls_success = 0
        self.api_calls_failed = 0

        self.records_completed = 0
        self.records_success = 0
        self.records_failed = 0
        self.records_invalid_json = 0
        self.records_skipped = 0

        self.started_at = time.time()
        

    def _elapsed_text(
        self
    ):
        elapsed = int(
            time.time() - self.started_at
        )

        minutes = elapsed // 60
        seconds = elapsed % 60

        return f"{minutes:02d}m {seconds:02d}s"

    def _print(
        self,
        message
    ):
        print(
            message,
            flush=True
        )

    def print_run_start(
        self,
        run_id,
        process_limit,
        max_workers,
        primary_model,
        fallback_models
    ):
        self._print(
            "\n========== GEMINI RUN STARTED =========="
        )

        self._print(
            f"Run ID        : {run_id}"
        )

        self._print(
            f"Total Selected: {self.total_records}"
        )

        self._print(
            f"Process Limit : {'ALL' if process_limit <= 0 else process_limit}"
        )

        self._print(
            f"Workers       : {max_workers}"
        )

        self._print(
            f"Primary Model : {primary_model}"
        )

        self._print(
            f"Fallbacks     : {fallback_models}"
        )

        self._print(
            f"API Limit     : {TRIAL_API_LIMIT_PER_MINUTE}/min"
        )

        self._print(
            f"Token Limit   : {TRIAL_TOKENS_PER_MINUTE if TRIAL_TOKENS_PER_MINUTE is not None else 'UNLIMITED'}/min"
        )

        self._print(
            f"Remote Count  : {'ON' if USE_REMOTE_TOKEN_COUNT else 'OFF'}"
        )

        self._print(
            "========================================\n"
        )

    def api_call_started(
        self,
        question_id,
        subject,
        model_name,
        attempt,
        total_attempt,
        token_count=None,
        image_count=0,
        curriculum_file_count=0
    ):
        with self.lock:
            self.api_calls_started += 1

            self._print(
                f"[API CALL STARTED] "
                f"Call={self.api_calls_started} | "
                f"QID={question_id} | "
                f"Subject={subject} | "
                f"Model={model_name} | "
                f"Attempt={attempt} | "
                f"TotalAttempt={total_attempt} | "
                f"Tokens={token_count} | "
                f"Images={image_count} | "
                f"CurriculumFiles={curriculum_file_count}"
            )

    def api_call_success(
        self,
        question_id,
        model_name,
        attempt,
        total_attempt,
        status,
        usage=None
    ):
        usage = usage or {}

        with self.lock:
            self.api_calls_success += 1

            self._print(
                f"[API RESPONSE RECEIVED] "
                f"QID={question_id} | "
                f"Model={model_name} | "
                f"Attempt={attempt} | "
                f"TotalAttempt={total_attempt} | "
                f"Status={status} | "
                f"InputTokens={usage.get('prompt_token_count')} | "
                f"OutputTokens={usage.get('candidates_token_count')} | "
                f"TotalTokens={usage.get('total_token_count')}"
            )

    def api_call_failed(
        self,
        question_id,
        model_name,
        attempt,
        total_attempt,
        error,
        wait_time=None
    ):
        with self.lock:
            self.api_calls_failed += 1

            error_type = (
                error.get("error_type")
                if isinstance(error, dict)
                else type(error).__name__
            )

            error_message = (
                error.get("error_message")
                if isinstance(error, dict)
                else str(error)
            )
            quota_exceeded = bool(
                error.get("quota_exceeded")
            ) if isinstance(error, dict) else is_quota_error(error)

            self._print(
                f"[API CALL FAILED] "
                f"QID={question_id} | "
                f"Model={model_name} | "
                f"Attempt={attempt} | "
                f"TotalAttempt={total_attempt} | "
                f"ErrorType={error_type} | "
                f"Reason={error_message} | "
                f"QuotaExceeded={'Yes' if quota_exceeded else 'No'} | "
                f"RetryAfter={wait_time}s"
            )

    def model_switch(
        self,
        question_id,
        from_model,
        to_model,
        reason
    ):
        with self.lock:
            self._print(
                f"[MODEL SWITCH] "
                f"QID={question_id} | "
                f"From={from_model} | "
                f"To={to_model} | "
                f"Reason={reason}"
            )

    def record_done(
        self,
        result
    ):
        status = result.get(
            "status"
        )

        question_id = result.get(
            "question_id"
        )

        model_name = result.get(
            "model_name"
        )

        attempts_used = result.get(
            "attempts_used"
        )

        with self.lock:
            self.records_completed += 1

            if status == "success":
                self.records_success += 1

            elif status == "invalid_json_response":
                self.records_invalid_json += 1
                self.records_failed += 1

            elif str(status or "").startswith("failed"):
                self.records_failed += 1

            elif status == "skipped":
                self.records_skipped += 1

            else:
                self.records_failed += 1

            remaining = (
                self.total_records
                -
                self.records_completed
            )

            self._print(
                "\n[PROGRESS]"
                f" Completed={self.records_completed}/{self.total_records}"
                f" | Remaining={remaining}"
                f" | Success={self.records_success}"
                f" | Failed={self.records_failed}"
                f" | InvalidJSON={self.records_invalid_json}"
                f" | Skipped={self.records_skipped}"
                f" | APIStarted={self.api_calls_started}"
                f" | APISuccess={self.api_calls_success}"
                f" | APIFailedAttempts={self.api_calls_failed}"
                f" | Elapsed={self._elapsed_text()}"
            )

            self._print(
                f"[RECORD DONE] "
                f"Status={status} | "
                f"QID={question_id} | "
                f"Model={model_name} | "
                f"Attempts={attempts_used} | "
                f"Reason={self._result_reason(result)}\n"
            )

    def _result_reason(
        self,
        result
    ):
        if not isinstance(
            result,
            dict
        ):
            return "Unknown"

        status = result.get(
            "status"
        )

        if status == "success":
            validation = result.get(
                "validation",
                {}
            )
            if isinstance(
                validation,
                dict
            ) and not validation.get("valid", True):
                errors = validation.get(
                    "errors",
                    []
                )
                return "; ".join(
                    str(item)
                    for item in errors[:3]
                ) or "validation failed"

            return "success"

        error = result.get(
            "error"
        )

        if isinstance(
            error,
            dict
        ):
            return summarize_error_reason(
                error
            )

        reason = result.get(
            "reason"
        )
        if reason:
            return str(
                reason
            )

        validation = result.get(
            "validation"
        )
        if isinstance(
            validation,
            dict
        ):
            errors = validation.get(
                "errors",
                []
            )
            if errors:
                return "; ".join(
                    str(item)
                    for item in errors[:3]
                )

        return status or "Unknown"

    def worker_crashed(
        self,
        error,
        record_count=1
    ):
        with self.lock:
            self.records_completed += record_count
            self.records_failed += record_count

            self._print(
                "\n[WORKER CRASHED]"
            )

            self._print(
                f"ErrorType={type(error).__name__}"
            )

            self._print(
                f"AffectedRecords={record_count}"
            )

            self._print(
                f"Reason={str(error)}"
            )

            self._print(
                f"Completed={self.records_completed}/{self.total_records}"
                f" | Success={self.records_success}"
                f" | Failed={self.records_failed}"
                f" | InvalidJSON={self.records_invalid_json}"
                f" | Skipped={self.records_skipped}"
                f" | APIStarted={self.api_calls_started}"
                f" | APISuccess={self.api_calls_success}"
                f" | APIFailedAttempts={self.api_calls_failed}"
                f" | Elapsed={self._elapsed_text()}\n"
            )

    def print_interrupt_summary(
        self,
        reason="Interrupted"
    ):
        with self.lock:
            self._print(
                "\n========== RUN INTERRUPTED =========="
            )
            self._print(
                f"Reason        : {reason}"
            )
            self._print(
                f"Completed     : {self.records_completed}/{self.total_records}"
            )
            self._print(
                f"Success       : {self.records_success}"
            )
            self._print(
                f"Failed        : {self.records_failed}"
            )
            self._print(
                f"Invalid JSON  : {self.records_invalid_json}"
            )
            self._print(
                f"Skipped       : {self.records_skipped}"
            )
            self._print(
                f"API Started   : {self.api_calls_started}"
            )
            self._print(
                f"API Success   : {self.api_calls_success}"
            )
            self._print(
                f"API Failed    : {self.api_calls_failed}"
            )
            self._print(
                f"Elapsed       : {self._elapsed_text()}"
            )
            self._print(
                "=====================================\n"
            )


def load_json_file(
    file_path,
    default=None
):
    file_path = Path(
        file_path
    )

    if default is None:
        default = {}

    if not file_path.exists():
        return default

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(
            f
        )


def is_prompt_storage_file(file_path):
    file_path = Path(file_path)

    if file_path.suffix.lower() != ".json":
        return False

    return file_path.name not in {
        "summary.json",
        "failed_prompt_preview.json"
    }


def list_prompt_storage_files(root_path):
    root_path = Path(root_path)

    if not root_path.exists():
        return []

    return sorted(
        file_path
        for file_path in root_path.rglob("*.json")
        if is_prompt_storage_file(file_path)
    )


def resolve_prompt_preview_root():
    output_root = PROJECT_ROOT / "output"

    discovered = []
    scanned = []

    if output_root.exists():
        search_roots = [
            child
            for child in output_root.iterdir()
            if child.is_dir()
        ]

        for search_root in search_roots:
            prompt_files = list_prompt_storage_files(
                search_root
            )

            scanned.append(
                {
                    "source": "scanned",
                    "path": search_root,
                    "prompt_storage_file_count": len(prompt_files),
                    "newest_prompt_storage_timestamp": (
                        max(
                            prompt_file.stat().st_mtime
                            for prompt_file in prompt_files
                        )
                        if prompt_files
                        else None
                    )
                }
            )

            if not prompt_files:
                continue

            discovered.append(
                {
                    "source": "discovered",
                    "path": search_root,
                    "prompt_storage_file_count": len(prompt_files),
                    "newest_prompt_storage_timestamp": scanned[-1][
                        "newest_prompt_storage_timestamp"
                    ]
                }
            )

    discovered = sorted(
        discovered,
        key=lambda item: (
            item["prompt_storage_file_count"],
            item["newest_prompt_storage_timestamp"]
        ),
        reverse=True
    )

    candidates = discovered or scanned or [
        {
            "source": "default_missing",
            "path": PROMPT_PREVIEW_ROOT,
            "prompt_storage_file_count": 0,
            "newest_prompt_storage_timestamp": None
        }
    ]

    diagnostics = []

    for candidate in candidates:
        candidate_path = Path(
            candidate["path"]
        )

        prompt_file_count = candidate.get(
            "prompt_storage_file_count",
            0
        )

        if (
            prompt_file_count == 0
            and
            candidate_path.exists()
        ):
            prompt_file_count = len(
                list_prompt_storage_files(
                    candidate_path
                )
            )

        diagnostics.append(
            {
                "source": candidate["source"],
                "path": str(candidate_path),
                "exists": candidate_path.exists(),
                "prompt_storage_file_count": prompt_file_count,
                "newest_prompt_storage_timestamp": candidate.get(
                    "newest_prompt_storage_timestamp"
                )
            }
        )

        if (
            candidate_path.exists()
            and
            prompt_file_count > 0
        ):
            return candidate_path, diagnostics

    return PROMPT_PREVIEW_ROOT, diagnostics


def summarize_selected_records(
    records,
    prompt_preview_root,
    prompt_preview_diagnostics,
    selection_metadata=None,
    previous_success_lookup_summary=None
):
    selection_metadata = selection_metadata or {}
    previous_success_lookup_summary = (
        previous_success_lookup_summary
        or {}
    )
    by_subject = {}
    by_question_type = {}
    image_statuses = {}
    source_files = {}

    prompt_missing = 0
    image_records = 0
    total_images = 0
    resolved_images = 0
    unresolved_images = 0
    missing_lo_id_mapping = 0

    for record in records:
        subject = get_record_subject(
            record
        )

        question_type = get_record_question_type(
            record
        )

        by_subject[subject] = by_subject.get(
            subject,
            0
        ) + 1

        by_question_type[question_type] = by_question_type.get(
            question_type,
            0
        ) + 1

        source_file = record.get(
            "_source_file",
            "unknown"
        )

        source_files[source_file] = source_files.get(
            source_file,
            0
        ) + 1

        if not get_record_lo_id(record):
            missing_lo_id_mapping += 1

        if not get_record_prompt(
            record
        ):
            prompt_missing += 1

        images = get_record_images(
            record
        )

        if images:
            image_records += 1

        total_images += len(
            images
        )

        for image in images:
            status = str(
                image.get("status")
                or "unknown"
            )

            image_statuses[status] = image_statuses.get(
                status,
                0
            ) + 1

            if image.get("exists") is True:
                resolved_images += 1
            else:
                unresolved_images += 1

    return {
        "generated_at": datetime.now().isoformat(),
        "prompt_preview_root": str(prompt_preview_root),
        "prompt_preview_diagnostics": prompt_preview_diagnostics,
        "total_records": len(records),
        "skip_previous_successes_enabled": bool(
            previous_success_lookup_summary.get(
                "enabled"
            )
        ),
        "previous_success_lookup_runs_scanned": previous_success_lookup_summary.get(
            "run_ids_scanned",
            []
        ),
        "previous_success_lookup_subject_counts": previous_success_lookup_summary.get(
            "subject_counts",
            {}
        ),
        "skipped_excluded_subjects": selection_metadata.get(
            "excluded_subject_counts",
            {}
        ),
        "skipped_previously_successful": sum(
            int(value or 0)
            for value in selection_metadata.get(
                "previous_success_counts",
                {}
            ).values()
        ),
        "skipped_previously_successful_by_subject": selection_metadata.get(
            "previous_success_counts",
            {}
        ),
        "missing_lo_id_mapping": missing_lo_id_mapping,
        "prompt_missing": prompt_missing,
        "records_with_images": image_records,
        "total_images": total_images,
        "resolved_images": resolved_images,
        "unresolved_images": unresolved_images,
        "by_subject": dict(
            sorted(
                by_subject.items()
            )
        ),
        "by_question_type": dict(
            sorted(
                by_question_type.items()
            )
        ),
        "image_statuses": dict(
            sorted(
                image_statuses.items()
            )
        ),
        "source_files": dict(
            sorted(
                source_files.items()
            )
        )
    }


def build_lesson_context_manifest(records):
    seen_lo_ids = set()
    manifest_rows = []

    for record in records:
        lo_id = get_record_lo_id(record)

        if lo_id in seen_lo_ids:
            continue

        seen_lo_ids.add(lo_id)

        lesson_context = load_lesson_context(lo_id)
        lesson_context_text = build_lesson_context_text(
            lesson_context
        )

        manifest_rows.append(
            {
                "lo_id": lo_id,
                "available": lesson_context.get("available", False),
                "lesson_dir": lesson_context.get("lesson_dir"),
                "json_file_count": len(
                    lesson_context.get("json_files", [])
                ),
                "section_count": len(
                    lesson_context.get("sections", [])
                ),
                "json_files": lesson_context.get("json_files", []),
                "lesson_context_text": lesson_context_text
            }
        )

    return manifest_rows


def clip_preview_text(
    value,
    max_chars=600
):
    text = str(value or "").strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def build_lesson_attachment_manifest(records):
    manifest_rows = []

    for record in records:
        question_id = get_batch_question_id(record)
        lo_id = get_record_lo_id(record)
        lesson_context = load_lesson_context(lo_id)
        lesson_context_text = build_lesson_context_text(
            lesson_context
        )

        manifest_rows.append(
            {
                "question_id": question_id,
                "source_file": record.get("_source_file"),
                "subject": get_record_subject(record),
                "question_type": get_record_question_type(record),
                "lo_id": lo_id,
                "lesson_context_attached": bool(lesson_context_text),
                "lesson_context_available": lesson_context.get("available", False),
                "lesson_context_section_count": len(
                    lesson_context.get("sections", [])
                ),
                "lesson_context_char_count": len(lesson_context_text),
                "lesson_context_preview": clip_preview_text(lesson_context_text),
                "prompt_char_count": len(str(get_record_prompt(record) or "")),
                "image_count": len(get_record_images(record))
            }
        )

    return manifest_rows


def build_batch_lesson_attachment_manifest(batches):
    rows = []

    for batch_number, batch in enumerate(batches, start=1):
        records = batch.get("records", [])
        first_record = records[0] if records else {}
        lo_id = get_record_lo_id(first_record)
        lesson_context = load_lesson_context(lo_id)
        lesson_context_text = build_lesson_context_text(
            lesson_context
        )

        rows.append(
            {
                "batch_id": f"batch_{batch_number:06d}",
                "lo_id": lo_id,
                "subject": get_batch_subject(first_record),
                "question_count": len(records),
                "question_ids": [
                    get_batch_question_id(record)
                    for record in records
                ],
                "lesson_context_attached": bool(lesson_context_text),
                "lesson_context_available": lesson_context.get("available", False),
                "lesson_context_section_count": len(
                    lesson_context.get("sections", [])
                ),
                "lesson_context_char_count": len(lesson_context_text),
                "lesson_context_preview": clip_preview_text(lesson_context_text)
            }
        )

    return rows


def write_assembled_request_previews(
    reporter,
    batches
):
    preview_root = reporter.report_root / "assembled_requests"
    preview_root.mkdir(parents=True, exist_ok=True)

    for batch_number, batch in enumerate(
        batches[:max(0, ASSEMBLED_REQUEST_PREVIEW_LIMIT)],
        start=1
    ):
        records = batch.get("records", [])
        first_record = records[0] if records else {}
        lo_id = get_record_lo_id(first_record)
        lesson_context = load_lesson_context(lo_id)
        lesson_context_text = build_lesson_context_text(lesson_context)
        curriculum_result = resolve_curriculum_files_for_record(
            client=None,
            record=first_record,
            uploaded_files=load_json_file(
                UPLOADED_FILES_PATH,
                default={}
            ),
            min_grade=1,
            max_grade=12
        )
        curriculum_references = get_curriculum_file_references_for_report(
            curriculum_result
        )
        question_ids = [
            get_batch_question_id(record)
            for record in records
        ]

        assembled_lines = [
            f"BATCH ID: batch_{batch_number:06d}",
            f"SUBJECT: {get_batch_subject(first_record)}",
            f"LO_ID: {lo_id}",
            f"QUESTION COUNT: {len(records)}",
            ""
        ]

        assembled_lines.extend(
            [
                "===== CURRICULUM REFERENCES =====",
                json.dumps(
                    curriculum_references,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                ),
                ""
            ]
        )

        if lesson_context_text:
            assembled_lines.extend(
                [
                    "===== LESSON CONTEXT =====",
                    lesson_context_text,
                    ""
                ]
            )

        assembled_lines.extend(
            [
                "===== BATCH INSTRUCTION =====",
                build_batch_instruction(
                    get_batch_subject(first_record),
                    question_ids,
                    grade=first_record.get("grade")
                ),
                ""
            ]
        )

        for record in records:
            pil_images, image_report = load_images_for_record(
                record
            )

            assembled_lines.extend(
                [
                    f"===== QUESTION {get_batch_question_id(record)} =====",
                    build_question_text(record),
                    ""
                ]
            )

            if image_report:
                assembled_lines.extend(
                    [
                        f"===== IMAGES {get_batch_question_id(record)} =====",
                        json.dumps(
                            image_report,
                            ensure_ascii=False,
                            indent=2,
                            default=str
                        ),
                        ""
                    ]
                )

                loaded_index = 0

                for image_index, image_info in enumerate(
                    image_report,
                    start=1
                ):
                    if not image_info.get(
                        "loaded_for_gemini"
                    ):
                        continue

                    image_obj = None

                    if loaded_index < len(pil_images):
                        image_obj = pil_images[loaded_index]

                    assembled_lines.append(
                        f"IMAGE FOR QUESTION {get_batch_question_id(record)}: image-{image_index} follows immediately."
                    )

                    if image_obj is not None:
                        assembled_lines.append(
                            f"[PIL_IMAGE mode={getattr(image_obj, 'mode', None)} size={getattr(image_obj, 'size', None)}]"
                        )

                    loaded_index += 1

                assembled_lines.append("")

            assembled_lines.append(
                f"END QUESTION {get_batch_question_id(record)}"
            )
            assembled_lines.append("")

        with open(
            preview_root / f"batch_{batch_number:06d}.txt",
            "w",
            encoding="utf-8"
        ) as f:
            f.write("\n".join(assembled_lines))


def print_input_manifest(
    manifest
):
    print(
        "\n========== INPUT MANIFEST ==========",
        flush=True
    )

    print(
        f"Prompt Root    : {manifest.get('prompt_preview_root')}",
        flush=True
    )

    print(
        f"Records        : {manifest.get('total_records')}",
        flush=True
    )

    print(
        f"Prev Successes : {manifest.get('skipped_previously_successful')} "
        f"(enabled={manifest.get('skip_previous_successes_enabled')})",
        flush=True
    )

    print(
        f"Missing Prompts: {manifest.get('prompt_missing')}",
        flush=True
    )

    print(
        f"Image Records  : {manifest.get('records_with_images')}",
        flush=True
    )

    print(
        f"Images         : {manifest.get('total_images')} "
        f"(resolved={manifest.get('resolved_images')}, "
        f"unresolved={manifest.get('unresolved_images')})",
        flush=True
    )

    print(
        f"By Subject     : {manifest.get('by_subject')}",
        flush=True
    )

    print(
        f"Skipped Prev   : {manifest.get('skipped_previously_successful_by_subject')}",
        flush=True
    )

    print(
        f"By Type        : {manifest.get('by_question_type')}",
        flush=True
    )

    print(
        "====================================\n",
        flush=True
    )


def clean_json_response(
    raw_response
):
    clean_text = str(
        raw_response or ""
    ).strip()

    clean_text = re.sub(
        r"^```json",
        "",
        clean_text,
        flags=re.IGNORECASE
    )

    clean_text = re.sub(
        r"^```",
        "",
        clean_text
    )

    clean_text = clean_text.replace(
        "```",
        ""
    ).strip()

    return clean_text


def parse_json_response(
    raw_response
):
    clean_text = clean_json_response(
        raw_response
    )

    parsed = json.loads(
        clean_text
    )

    return parsed, clean_text


def get_usage_metadata_dict(
    response,
    estimated_prompt_tokens=None
):
    usage = getattr(
        response,
        "usage_metadata",
        None
    )

    if not usage:
        return {
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "prompt_token_count": None,
            "candidates_token_count": None,
            "thoughts_token_count": None,
            "cached_content_token_count": None,
            "total_token_count": None,
            "raw_usage_metadata": None
        }

    return {
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "prompt_token_count": getattr(
            usage,
            "prompt_token_count",
            None
        ),
        "candidates_token_count": getattr(
            usage,
            "candidates_token_count",
            None
        ),
        "thoughts_token_count": getattr(
            usage,
            "thoughts_token_count",
            None
        ),
        "cached_content_token_count": getattr(
            usage,
            "cached_content_token_count",
            None
        ),
        "total_token_count": getattr(
            usage,
            "total_token_count",
            None
        ),
        "raw_usage_metadata": str(
            usage
        )
    }


def get_record_question_id(
    record
):
    return (
        record.get("question_id")
        or record.get("id")
        or record.get("externalId")
        or "unknown_question_id"
    )


def get_record_subject(
    record
):
    return (
        record.get("folder_subject")
        or record.get("subject")
        or "UNKNOWN"
    )


def normalize_subject_name(
    subject
):
    subject = str(
        subject or "UNKNOWN"
    ).strip().upper()

    subject_map = {
        "MATH_EN": "MATH",
        "SCIENCE_EN": "SCIENCE",
        "BIOLOGY_EN": "BIOLOGY",
        "CHEMISTRY_EN": "CHEMISTRY",
        "PHYSICS_EN": "PHYSICS"
    }

    return subject_map.get(
        subject,
        subject
    )


def get_record_question_type(
    record
):
    return (
        record.get("question_type")
        or record.get("type")
        or "UNKNOWN"
    )


def get_record_prompt(
    record
):
    normalized_input = record.get(
        "normalized_input"
    )

    if isinstance(normalized_input, dict):
        try:
            return build_single_prompt(
                normalized_input
            )
        except Exception:
            pass

    return (
        record.get("prompt")
        or record.get("gemini_prompt")
        or record.get("text")
        or ""
    )


def get_record_images(
    record
):
    images = record.get(
        "images"
    )

    if isinstance(
        images,
        list
    ) and images:
        return images

    normalized_input = record.get(
        "normalized_input"
    )

    if isinstance(
        normalized_input,
        dict
    ):
        normalized_images = normalized_input.get(
            "images"
        )

        if isinstance(
            normalized_images,
            list
        ):
            return normalized_images

    if isinstance(
        images,
        list
    ):
        return images

    return []


def load_images_for_record(
    record
):
    images = get_record_images(
        record
    )

    pil_images = []
    image_report = []

    for image_info in images:
        local_path = image_info.get(
            "local_path"
        )

        exists = image_info.get(
            "exists"
        )

        if not local_path or exists is not True:
            image_report.append(
                {
                    **image_info,
                    "loaded_for_gemini": False,
                    "load_error": "local_path_missing_or_file_not_resolved"
                }
            )
            continue

        try:
            image = Image.open(
                local_path
            )

            image.load()

            pil_images.append(
                image
            )

            image_report.append(
                {
                    **image_info,
                    "loaded_for_gemini": True,
                    "load_error": None
                }
            )

        except Exception as e:
            image_report.append(
                {
                    **image_info,
                    "loaded_for_gemini": False,
                    "load_error": str(e)
                }
            )

    return pil_images, image_report


def build_contents(
    curriculum_files,
    pil_images,
    prompt,
    lesson_context_text=None
):
    contents = []

    for curriculum_file in curriculum_files or []:
        contents.append(
            curriculum_file
        )

    for image in pil_images or []:
        contents.append(
            image
        )

    if lesson_context_text:
        contents.append(
            lesson_context_text
        )

    if prompt:
        contents.append(
            prompt
        )

    return contents


def should_start_with_fallback_model(
    subject,
    prompt,
    image_count
):
    normalized_subject = str(
        subject or ""
    ).strip().upper()

    if image_count >= DIRECT_FLASH_IMAGE_THRESHOLD:
        return True

    return (
        normalized_subject in {
            "SCIENCE",
            "SCIENCE_EN",
            "BIOLOGY",
            "BIOLOGY_EN",
            "CHEMISTRY",
            "CHEMISTRY_EN",
            "PHYSICS",
            "PHYSICS_EN"
        }
        and len(prompt or "") >= DIRECT_FLASH_COMPLEX_PROMPT_CHARS
    )


def build_models_to_try(
    prefer_fallback=False
):
    ordered_models = []

    if prefer_fallback and FALLBACK_MODELS:
        ordered_models.extend(
            FALLBACK_MODELS
        )
        ordered_models.append(
            PRIMARY_MODEL
        )
    else:
        ordered_models.append(
            PRIMARY_MODEL
        )
        ordered_models.extend(
            FALLBACK_MODELS
        )

    models = []

    for model_name in ordered_models:
        normalized = str(
            model_name or ""
        ).strip()

        if normalized and normalized not in models:
            models.append(
                normalized
            )

    return models


def build_generation_config():
    if not FORCE_JSON_RESPONSE:
        return None

    return genai.types.GenerateContentConfig(
        responseMimeType="application/json"
    )


def count_tokens_safe(
    client,
    model_name,
    contents,
    progress=None,
    question_id=None
):
    try:
        token_response = client.models.count_tokens(
            model=model_name,
            contents=contents
        )

        return token_response.total_tokens, None

    except Exception as e:
        return None, {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "error_repr": repr(e)
        }


def estimate_tokens_for_request(
    client,
    model_name,
    contents,
    local_estimated_tokens,
    question_id=None,
    use_remote_count=USE_REMOTE_TOKEN_COUNT,
    progress=None
):
    if use_remote_count and client is not None:
        return count_tokens_safe(
            client=client,
            model_name=model_name,
            contents=contents,
            progress=progress,
            question_id=question_id
        )

    return int(local_estimated_tokens or 0), {
        "error_type": "RemoteTokenCountDisabled",
        "error_message": (
            "AI_ENGINE_USE_REMOTE_TOKEN_COUNT=false; "
            "using local token estimate."
        ),
        "error_repr": None
    }


def build_error_payload(
    error
):
    error_message = str(error) if error else None
    quota_exceeded = is_quota_error(
        error
    )

    if quota_exceeded and error_message:
        error_message = f"Quota exceeded: {error_message}"

    return {
        "error_type": type(error).__name__ if error else None,
        "error_message": error_message,
        "error_repr": repr(error) if error else None,
        "retry_after_seconds": extract_retry_delay_seconds(error),
        "quota_exceeded": quota_exceeded,
        "traceback": traceback.format_exc()
    }


def build_api_limit_payload(
    reporter,
    question_id,
    subject,
    question_type,
    prompt,
    images,
    curriculum_references,
    model_name=None,
    limit_error=None
):
    if isinstance(limit_error, ApiCallLimitReached):
        limit_reason = (
            f"AI_ENGINE_TRIAL_API_LIMIT_PER_{limit_error.limit_scope.upper()}="
            f"{limit_error.limit_value} reached."
        )
    else:
        limit_reason = "Gemini API rate limit reached."

    return {
        "timestamp": datetime.now().isoformat(),
        "run_id": reporter.run_id,
        "status": "skipped_api_call_limit_reached",
        "question_id": question_id,
        "subject": subject,
        "question_type": question_type,
        "model_name": model_name,
        "attempts_used": 0,
        "prompt": prompt,
        "images": images,
        "curriculum_references": curriculum_references,
        "reason": (
            f"{limit_reason} "
            "Adjust the trial limit env vars to change it."
        ),
        "usage": empty_usage()
    }


def request_run_stop(reason):
    RUN_STATE["stop_requested"] = True
    RUN_STATE["stop_reason"] = reason


def is_run_stop_requested():
    return bool(
        RUN_STATE.get("stop_requested")
    )


def should_switch_model_on_error(
    error
):
    return is_quota_error(
        error
    )


def extract_retry_delay_seconds(
    error
):
    if not error:
        return None

    error_text = str(
        error
    )

    patterns = [
        r"retryDelay['\"]?\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)s",
        r"retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        r"RetryAfter=([0-9]+(?:\.[0-9]+)?)s"
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            error_text,
            flags=re.IGNORECASE
        )

        if not match:
            continue

        try:
            return int(
                float(
                    match.group(1)
                )
            ) + 1

        except Exception:
            continue

    return None


def sleep_before_retry(
    attempt,
    error=None
):
    wait_time = RETRY_BASE_SECONDS ** attempt

    retry_after_seconds = extract_retry_delay_seconds(
        error
    )

    if retry_after_seconds is not None:
        wait_time = max(
            wait_time,
            retry_after_seconds
        )

    time.sleep(
        wait_time
    )

    return wait_time


def call_gemini_with_model_switch(
    client,
    reporter,
    record,
    uploaded_files,
    progress
):
    question_id = get_record_question_id(
        record
    )

    subject = get_record_subject(
        record
    )

    question_type = get_record_question_type(
        record
    )

    prompt = get_record_prompt(
        record
    )

    if not prompt:
        failure_payload = {
            "timestamp": datetime.now().isoformat(),
            "run_id": reporter.run_id,
            "status": "failed_prompt_missing",
            "question_id": question_id,
            "subject": subject,
            "question_type": question_type,
            "model_name": None,
            "attempts_used": 0,
            "prompt": prompt,
            "images": [],
            "curriculum_references": None,
            "error": {
                "error_type": "PromptMissing",
                "error_message": "Prompt is missing in prompt preview record.",
                "error_repr": None
            },
            "usage": {
                "estimated_prompt_tokens": None,
                "prompt_token_count": None,
                "candidates_token_count": None,
                "thoughts_token_count": None,
                "cached_content_token_count": None,
                "total_token_count": None
            }
        }

        reporter.log_failure(
            failure_payload
        )

        return failure_payload

    curriculum_result = resolve_curriculum_files_for_record(
        client=client,
        record=record,
        uploaded_files=uploaded_files,
        min_grade=1,
        max_grade=12
    )

    curriculum_files = get_curriculum_files_for_contents(
        curriculum_result
    )

    curriculum_references = get_curriculum_file_references_for_report(
        curriculum_result
    )
    with OUTCOME_KEY_CACHE_LOCK:
        allowed_outcome_keys = load_allowed_outcome_keys(
            project_root=PROJECT_ROOT,
            curriculum_references=curriculum_references,
            uploaded_files=uploaded_files,
            cache=OUTCOME_KEY_CACHE
        )
    lo_id = get_record_lo_id(record)
    lesson_context = load_lesson_context(lo_id)
    lesson_context_text = build_lesson_context_text(
        lesson_context
    )

    pil_images, image_report = load_images_for_record(
        record
    )

    models_to_try = build_models_to_try(
        prefer_fallback=should_start_with_fallback_model(
            subject=subject,
            prompt=prompt,
            image_count=len(image_report)
        )
    )
    generation_config = build_generation_config()

    total_attempts_used = 0
    last_error_payload = None
    last_model_name = None

    for model_index, model_name in enumerate(
        models_to_try
    ):
        last_model_name = model_name

        contents = build_contents(
            curriculum_files=curriculum_files,
            pil_images=pil_images,
            prompt=prompt,
            lesson_context_text=lesson_context_text
        )

        try:
            estimated_prompt_tokens, token_error = estimate_tokens_for_request(
                client=client,
                model_name=model_name,
                contents=contents,
                local_estimated_tokens=local_detail["estimated_prompt_tokens"],
                progress=progress,
                question_id=question_id
            )
        except ApiCallLimitReached as e:
            request_run_stop(
                str(e)
            )
            skipped_payload = build_api_limit_payload(
                reporter=reporter,
                question_id=question_id,
                subject=subject,
                question_type=question_type,
                prompt=prompt,
                images=image_report,
                curriculum_references=curriculum_references,
                model_name=model_name,
                limit_error=e
            )
            reporter.log_skipped(
                skipped_payload
            )
            return skipped_payload

        for attempt in range(
            1,
            MAX_RETRIES_PER_MODEL + 1
        ):
            total_attempts_used += 1

            reporter.log_preflight_token_usage(
                {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "request_mode": "single",
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "total_attempt": total_attempts_used,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "token_count_error": token_error,
                    "image_count": len(image_report),
                    "curriculum_file_count": len(curriculum_files),
                    "lesson_context_attached": bool(lesson_context_text),
                    "lesson_context_char_count": len(lesson_context_text or "")
                }
            )

            attempt_payload = {
                "timestamp": datetime.now().isoformat(),
                "run_id": reporter.run_id,
                "question_id": question_id,
                "subject": subject,
                "question_type": question_type,
                "model_name": model_name,
                "model_attempt": attempt,
                "total_attempt": total_attempts_used,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "token_count_error": token_error,
                "image_count": len(image_report),
                "images": image_report,
                "curriculum_references": curriculum_references,
                "status": "attempt_started"
            }

            reporter.log_attempt(
                attempt_payload
            )

            try:
                acquire_api_slot(
                    progress=progress,
                    api_name="generate_content",
                    question_id=question_id,
                    model_name=model_name,
                    estimated_token_count=estimated_prompt_tokens
                )

                progress.api_call_started(
                    question_id=question_id,
                    subject=subject,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    token_count=estimated_prompt_tokens,
                    image_count=len(image_report),
                    curriculum_file_count=len(curriculum_files)
                )

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=generation_config
                )

                raw_response = response.text

                usage = get_usage_metadata_dict(
                    response=response,
                    estimated_prompt_tokens=estimated_prompt_tokens
                )

                parsed_response, clean_text = parse_json_response(
                    raw_response
                )

                validation = assess_gemini_response(
                    response=parsed_response,
                    subject=subject,
                    grade=record.get("grade"),
                    allowed_outcome_keys=(
                        allowed_outcome_keys
                        if curriculum_references.get("enabled")
                        else None
                    ),
                    min_confidence=MIN_CONFIDENCE
                )

                if not validation.get("valid"):
                    progress.api_call_success(
                        question_id=question_id,
                        model_name=model_name,
                        attempt=attempt,
                        total_attempt=total_attempts_used,
                        status="response_quality_retry",
                        usage=usage
                    )

                    retry_payload = {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "question_id": question_id,
                        "subject": subject,
                        "question_type": question_type,
                        "model_name": model_name,
                        "model_attempt": attempt,
                        "total_attempt": total_attempts_used,
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "status": "response_quality_retry",
                        "curriculum_references": curriculum_references,
                        "images": image_report,
                        "validation": validation,
                        "usage": usage
                    }

                    reporter.log_attempt(
                        retry_payload
                    )

                    last_error_payload = {
                        "error_type": "ResponseValidationError",
                        "error_message": "; ".join(
                            validation.get("errors", [])
                        ) or "Response quality validation failed.",
                        "error_repr": None,
                        "retry_reasons": validation.get("retry_reasons", [])
                    }

                    if model_index < len(models_to_try) - 1:
                        break

                    if FAIL_SCHEMA_VALIDATION:
                        raise ValueError(
                            f"Gemini schema validation failed: {validation.get('errors')}"
                        )

                    invalid_payload = {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "status": "response_validation_failed",
                        "question_id": question_id,
                        "subject": subject,
                        "question_type": question_type,
                        "model_name": model_name,
                        "model_attempt": attempt,
                        "attempts_used": total_attempts_used,
                        "prompt": prompt,
                        "images": image_report,
                        "curriculum_references": curriculum_references,
                        "raw_response": raw_response,
                        "clean_response": clean_text,
                        "parsed_response": parsed_response,
                        "validation": validation,
                        "error": last_error_payload,
                        "usage": usage
                    }

                    reporter.log_failure(
                        invalid_payload
                    )

                    return invalid_payload

                progress.api_call_success(
                    question_id=question_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    status="success",
                    usage=usage
                )

                success_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "status": "success",
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "attempts_used": total_attempts_used,
                    "prompt": prompt,
                    "images": image_report,
                    "curriculum_references": curriculum_references,
                    "raw_response": raw_response,
                    "clean_response": clean_text,
                    "parsed_response": parsed_response,
                    "validation": validation,
                    "usage": usage
                }

                reporter.log_success(
                    success_payload
                )

                return success_payload

            except ApiCallLimitReached as e:
                request_run_stop(
                    str(e)
                )
                skipped_payload = build_api_limit_payload(
                    reporter=reporter,
                    question_id=question_id,
                    subject=subject,
                    question_type=question_type,
                    prompt=prompt,
                    images=image_report,
                    curriculum_references=curriculum_references,
                    model_name=model_name,
                    limit_error=e
                )
                reporter.log_skipped(
                    skipped_payload
                )
                return skipped_payload

            except json.JSONDecodeError as e:
                raw_response = ""

                try:
                    raw_response = response.text

                except Exception:
                    raw_response = ""

                clean_text = clean_json_response(
                    raw_response
                )

                usage = get_usage_metadata_dict(
                    response=response,
                    estimated_prompt_tokens=estimated_prompt_tokens
                )

                error_payload = build_error_payload(
                    e
                )

                progress.api_call_success(
                    question_id=question_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    status="invalid_json_response",
                    usage=usage
                )

                invalid_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "status": "invalid_json_response",
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "attempts_used": total_attempts_used,
                    "prompt": prompt,
                    "images": image_report,
                    "curriculum_references": curriculum_references,
                    "raw_response": raw_response,
                    "clean_response": clean_text,
                    "error": error_payload,
                    "usage": usage
                }

                reporter.log_invalid_json(
                    invalid_payload
                )

                last_error_payload = {
                    **error_payload,
                    "retry_reasons": [
                        "invalid_json"
                    ]
                }

                if model_index < len(models_to_try) - 1:
                    break

                return invalid_payload

            except ServerError as e:
                last_error_payload = build_error_payload(
                    e
                )

                if should_switch_model_on_error(
                    e
                ):
                    progress.api_call_failed(
                        question_id=question_id,
                        model_name=model_name,
                        attempt=attempt,
                        total_attempt=total_attempts_used,
                        error=last_error_payload,
                        wait_time=0
                    )

                    retry_payload = {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "question_id": question_id,
                        "subject": subject,
                        "question_type": question_type,
                        "model_name": model_name,
                        "model_attempt": attempt,
                        "total_attempt": total_attempts_used,
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "status": "server_error_model_switch",
                        "wait_time_seconds": 0,
                        "error": last_error_payload,
                        "curriculum_references": curriculum_references,
                        "images": image_report
                    }

                    reporter.log_attempt(
                        retry_payload
                    )
                    break

                wait_time = sleep_before_retry(
                    attempt,
                    error=e
                )

                progress.api_call_failed(
                    question_id=question_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    error=last_error_payload,
                    wait_time=wait_time
                )

                retry_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "total_attempt": total_attempts_used,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "status": "server_error_retry",
                    "wait_time_seconds": wait_time,
                    "error": last_error_payload,
                    "curriculum_references": curriculum_references,
                    "images": image_report
                }

                reporter.log_attempt(
                    retry_payload
                )

            except ClientError as e:
                last_error_payload = build_error_payload(
                    e
                )

                if should_switch_model_on_error(
                    e
                ):
                    progress.api_call_failed(
                        question_id=question_id,
                        model_name=model_name,
                        attempt=attempt,
                        total_attempt=total_attempts_used,
                        error=last_error_payload,
                        wait_time=0
                    )

                    retry_payload = {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "question_id": question_id,
                        "subject": subject,
                        "question_type": question_type,
                        "model_name": model_name,
                        "model_attempt": attempt,
                        "total_attempt": total_attempts_used,
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "status": "client_error_model_switch",
                        "wait_time_seconds": 0,
                        "error": last_error_payload,
                        "curriculum_references": curriculum_references,
                        "images": image_report
                    }

                    reporter.log_attempt(
                        retry_payload
                    )
                    break

                wait_time = sleep_before_retry(
                    attempt,
                    error=e
                )

                progress.api_call_failed(
                    question_id=question_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    error=last_error_payload,
                    wait_time=wait_time
                )

                retry_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "total_attempt": total_attempts_used,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "status": "client_error_retry",
                    "wait_time_seconds": wait_time,
                    "error": last_error_payload,
                    "curriculum_references": curriculum_references,
                    "images": image_report
                }

                reporter.log_attempt(
                    retry_payload
                )

            except Exception as e:
                last_error_payload = build_error_payload(
                    e
                )

                wait_time = sleep_before_retry(
                    attempt,
                    error=e
                )

                progress.api_call_failed(
                    question_id=question_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    error=last_error_payload,
                    wait_time=wait_time
                )

                retry_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "question_id": question_id,
                    "subject": subject,
                    "question_type": question_type,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "total_attempt": total_attempts_used,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "status": "unexpected_error_retry",
                    "wait_time_seconds": wait_time,
                    "error": last_error_payload,
                    "curriculum_references": curriculum_references,
                    "images": image_report
                }

                reporter.log_attempt(
                    retry_payload
                )

        if model_index < len(models_to_try) - 1:
            next_model = models_to_try[
                model_index + 1
            ]

            progress.model_switch(
                question_id=question_id,
                from_model=model_name,
                to_model=next_model,
                reason=(
                    "Quota or rate limit reached."
                    if last_error_payload and last_error_payload.get("quota_exceeded")
                    else (
                        f"Response validation failed: {', '.join(last_error_payload.get('retry_reasons', []))}."
                        if last_error_payload and last_error_payload.get("error_type") == "ResponseValidationError"
                        else "Model failed after max retries."
                    )
                )
            )

            switch_payload = {
                "timestamp": datetime.now().isoformat(),
                "run_id": reporter.run_id,
                "question_id": question_id,
                "subject": subject,
                "question_type": question_type,
                "from_model": model_name,
                "to_model": next_model,
                "reason": (
                    "Quota or rate limit reached."
                    if last_error_payload and last_error_payload.get("quota_exceeded")
                    else (
                        f"Response validation failed: {', '.join(last_error_payload.get('retry_reasons', []))}."
                        if last_error_payload and last_error_payload.get("error_type") == "ResponseValidationError"
                        else "Model failed after max retries."
                    )
                ),
                "attempts_used_on_model": MAX_RETRIES_PER_MODEL,
                "total_attempts_used": total_attempts_used,
                "last_error": last_error_payload,
                "curriculum_references": curriculum_references,
                "images": image_report
            }

            reporter.log_model_switch(
                switch_payload
            )

    failure_payload = {
        "timestamp": datetime.now().isoformat(),
        "run_id": reporter.run_id,
        "status": "failed_after_all_models",
        "question_id": question_id,
        "subject": subject,
        "question_type": question_type,
        "model_name": last_model_name,
        "attempts_used": total_attempts_used,
        "prompt": prompt,
        "images": image_report,
        "curriculum_references": curriculum_references,
        "error": last_error_payload,
        "usage": {
            "estimated_prompt_tokens": None,
            "prompt_token_count": None,
            "candidates_token_count": None,
            "thoughts_token_count": None,
            "cached_content_token_count": None,
            "total_token_count": None
        }
    }

    reporter.log_failure(
        failure_payload
    )

    return failure_payload


def build_batch_contents(
    curriculum_files,
    records,
    subject
):
    question_ids = [
        get_batch_question_id(record)
        for record in records
    ]

    contents = list(
        curriculum_files or []
    )

    first_record = records[0] if records else {}
    lo_id = get_record_lo_id(first_record)
    lesson_context = load_lesson_context(lo_id)
    lesson_context_text = build_lesson_context_text(
        lesson_context
    )

    if lesson_context_text:
        contents.append(
            lesson_context_text
        )

    contents.append(
        build_batch_instruction(
            subject,
            question_ids,
            grade=first_record.get("grade")
        )
    )

    image_reports = {}

    for record in records:
        question_id = get_batch_question_id(
            record
        )

        contents.append(
            build_question_text(
                record
            )
        )

        pil_images, image_report = load_images_for_record(
            record
        )

        image_reports[question_id] = image_report
        loaded_index = 0

        for image_index, image_info in enumerate(
            image_report,
            start=1
        ):
            if not image_info.get(
                "loaded_for_gemini"
            ):
                continue

            contents.append(
                f"IMAGE FOR QUESTION {question_id}: image-{image_index} follows immediately."
            )
            contents.append(
                pil_images[loaded_index]
            )
            loaded_index += 1

        contents.append(
            f"END QUESTION {question_id}"
        )

    return contents, image_reports


def write_batch_reconciliation(
    reporter,
    payload
):
    with reporter.lock:
        reporter.append_json_array(
            reporter.report_root / "batch_reconciliations.json",
            payload
        )


def call_gemini_batch_with_model_switch(
    client,
    reporter,
    records,
    uploaded_files,
    progress,
    batch_id,
    batch_metadata=None
):
    first_record = records[0]
    subject = get_batch_subject(
        first_record
    )
    question_ids = [
        get_batch_question_id(record)
        for record in records
    ]

    if is_run_stop_requested():
        return {
            "status": "run_stop_requested",
            "batch_id": batch_id,
            "question_ids": question_ids,
            "subject": subject,
            "model_name": None,
            "attempts_used": 0,
            "curriculum_references": None,
            "image_reports": {},
            "usage": empty_usage(),
            "error": {
                "error_type": "RunStopRequested",
                "error_message": RUN_STATE.get("stop_reason"),
                "error_repr": None
            }
        }

    curriculum_result = resolve_curriculum_files_for_record(
        client=client,
        record=first_record,
        uploaded_files=uploaded_files,
        min_grade=1,
        max_grade=12
    )

    curriculum_files = get_curriculum_files_for_contents(
        curriculum_result
    )
    curriculum_references = get_curriculum_file_references_for_report(
        curriculum_result
    )
    lesson_context = load_lesson_context(
        get_record_lo_id(first_record)
    )
    lesson_context_text = build_lesson_context_text(
        lesson_context
    )

    with OUTCOME_KEY_CACHE_LOCK:
        allowed_outcome_keys = load_allowed_outcome_keys(
            project_root=PROJECT_ROOT,
            curriculum_references=curriculum_references,
            uploaded_files=uploaded_files,
            cache=OUTCOME_KEY_CACHE
        )

    models_to_try = build_models_to_try()
    generation_config = build_generation_config()

    total_attempts_used = 0
    last_error_payload = None
    last_model_name = None
    last_image_reports = {}
    batch_metadata = batch_metadata or build_batch_metadata_for_records(
        records=records
    )

    for model_index, model_name in enumerate(
        models_to_try
    ):
        last_model_name = model_name

        local_detail = estimate_batch_prompt_tokens_locally(
            batch=batch_metadata,
            subject=subject
        )
        contents, image_reports = build_batch_contents(
            curriculum_files=curriculum_files,
            records=records,
            subject=subject
        )
        last_image_reports = image_reports

        try:
            estimated_prompt_tokens, token_error = estimate_tokens_for_request(
                client=client,
                model_name=model_name,
                contents=contents,
                local_estimated_tokens=local_detail["estimated_prompt_tokens"],
                progress=progress,
                question_id=batch_id
            )
        except ApiCallLimitReached as e:
            request_run_stop(
                str(e)
            )
            return {
                "status": "batch_api_call_limit_reached",
                "batch_id": batch_id,
                "question_ids": question_ids,
                "subject": subject,
                "model_name": model_name,
                "attempts_used": total_attempts_used,
                "curriculum_references": curriculum_references,
                "image_reports": image_reports,
                "usage": empty_usage(),
                "error": {
                    "error_type": "ApiCallLimitReached",
                    "error_message": str(e),
                    "error_repr": None
                }
            }

        if (
            estimated_prompt_tokens is not None
            and estimated_prompt_tokens > BATCH_MAX_INPUT_TOKENS
            and len(records) > 1
        ):
            return {
                "status": "batch_input_too_large",
                "batch_id": batch_id,
                "question_ids": question_ids,
                "subject": subject,
                "model_name": model_name,
                "attempts_used": total_attempts_used,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "curriculum_references": curriculum_references,
                "image_reports": image_reports,
                "usage": empty_usage()
            }

        for attempt in range(
            1,
            MAX_RETRIES_PER_MODEL + 1
        ):
            total_attempts_used += 1

            reporter.log_preflight_token_usage(
                {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "request_mode": "batch",
                    "batch_id": batch_id,
                    "question_ids": question_ids,
                    "batch_size": len(records),
                    "subject": subject,
                    "model_name": model_name,
                    "model_attempt": attempt,
                    "total_attempt": total_attempts_used,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                    "token_count_error": token_error,
                    "image_count": sum(
                        len(items)
                        for items in image_reports.values()
                    ),
                    "curriculum_file_count": len(curriculum_files),
                    "lesson_context_attached": bool(lesson_context_text),
                    "lesson_context_char_count": len(lesson_context_text or "")
                }
            )

            attempt_payload = {
                "timestamp": datetime.now().isoformat(),
                "run_id": reporter.run_id,
                "batch_id": batch_id,
                "question_ids": question_ids,
                "batch_size": len(records),
                "subject": subject,
                "model_name": model_name,
                "model_attempt": attempt,
                "total_attempt": total_attempts_used,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "token_count_error": token_error,
                "image_count": sum(len(items) for items in image_reports.values()),
                "curriculum_references": curriculum_references,
                "status": "batch_attempt_started"
            }

            reporter.log_attempt(
                attempt_payload
            )

            response = None

            try:
                acquire_api_slot(
                    progress=progress,
                    api_name="generate_content",
                    question_id=batch_id,
                    model_name=model_name,
                    estimated_token_count=estimated_prompt_tokens
                )

                progress.api_call_started(
                    question_id=batch_id,
                    subject=subject,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    token_count=estimated_prompt_tokens,
                    image_count=sum(len(items) for items in image_reports.values()),
                    curriculum_file_count=len(curriculum_files)
                )

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=generation_config
                )

                raw_response = response.text
                usage = get_usage_metadata_dict(
                    response=response,
                    estimated_prompt_tokens=estimated_prompt_tokens
                )

                parsed_response, clean_text = parse_json_response(
                    raw_response
                )

                reconciliation = reconcile_batch_response(
                    parsed_response=parsed_response,
                    records=records,
                    allowed_outcome_keys=(
                        allowed_outcome_keys
                        if curriculum_references.get("enabled")
                        else None
                    ),
                    min_confidence=MIN_CONFIDENCE
                )

                if (
                    not reconciliation.get("valid")
                    and model_index < len(models_to_try) - 1
                ):
                    progress.api_call_success(
                        question_id=batch_id,
                        model_name=model_name,
                        attempt=attempt,
                        total_attempt=total_attempts_used,
                        status="batch_response_quality_retry",
                        usage=usage
                    )

                    last_error_payload = {
                        "error_type": "BatchResponseValidationError",
                        "error_message": "; ".join(
                            reconciliation.get("errors", [])
                        ) or "Batch response quality validation failed.",
                        "error_repr": None,
                        "retry_reasons": [
                            "invalid_response"
                        ]
                    }

                    write_batch_reconciliation(
                        reporter,
                        {
                            "timestamp": datetime.now().isoformat(),
                            "run_id": reporter.run_id,
                            "batch_id": batch_id,
                            "question_ids": question_ids,
                            "model_name": model_name,
                            "status": "response_quality_retry",
                            "validation": {
                                key: value
                                for key, value in reconciliation.items()
                                if key not in {"valid_results", "invalid_results"}
                            },
                            "valid_ids": sorted(reconciliation.get("valid_results", {})),
                            "invalid_ids": sorted(reconciliation.get("invalid_results", {})),
                            "usage": usage
                        }
                    )
                    break

                progress.api_call_success(
                    question_id=batch_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    status=(
                        "batch_success"
                        if reconciliation.get("valid")
                        else "batch_partial_or_invalid"
                    ),
                    usage=usage
                )

                write_batch_reconciliation(
                    reporter,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "batch_id": batch_id,
                        "question_ids": question_ids,
                        "model_name": model_name,
                        "status": (
                            "valid"
                            if reconciliation.get("valid")
                            else "partial_or_invalid"
                        ),
                        "validation": {
                            key: value
                            for key, value in reconciliation.items()
                            if key not in {"valid_results", "invalid_results"}
                        },
                        "valid_ids": sorted(reconciliation.get("valid_results", {})),
                        "invalid_ids": sorted(reconciliation.get("invalid_results", {})),
                        "usage": usage
                    }
                )

                return {
                    "status": "batch_response",
                    "batch_id": batch_id,
                    "question_ids": question_ids,
                    "subject": subject,
                    "model_name": model_name,
                    "attempts_used": total_attempts_used,
                    "raw_response": raw_response,
                    "clean_response": clean_text,
                    "parsed_response": parsed_response,
                    "reconciliation": reconciliation,
                    "curriculum_references": curriculum_references,
                    "image_reports": image_reports,
                    "usage": usage
                }

            except ApiCallLimitReached as e:
                request_run_stop(
                    str(e)
                )
                return {
                    "status": "batch_api_call_limit_reached",
                    "batch_id": batch_id,
                    "question_ids": question_ids,
                    "subject": subject,
                    "model_name": model_name,
                    "attempts_used": total_attempts_used,
                    "curriculum_references": curriculum_references,
                    "image_reports": image_reports,
                    "usage": empty_usage(),
                    "error": {
                        "error_type": "ApiCallLimitReached",
                        "error_message": str(e),
                        "error_repr": None
                    }
                }

            except json.JSONDecodeError as e:
                raw_response = ""

                try:
                    raw_response = response.text
                except Exception:
                    pass

                usage = get_usage_metadata_dict(
                    response=response,
                    estimated_prompt_tokens=estimated_prompt_tokens
                )

                progress.api_call_success(
                    question_id=batch_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    status="batch_invalid_json",
                    usage=usage
                )

                write_batch_reconciliation(
                    reporter,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "run_id": reporter.run_id,
                        "batch_id": batch_id,
                        "question_ids": question_ids,
                        "model_name": model_name,
                        "status": "invalid_json",
                        "error": build_error_payload(e),
                        "usage": usage
                    }
                )

                invalid_json_result = {
                    "status": "batch_invalid_json",
                    "batch_id": batch_id,
                    "question_ids": question_ids,
                    "subject": subject,
                    "model_name": model_name,
                    "attempts_used": total_attempts_used,
                    "raw_response": raw_response,
                    "clean_response": clean_json_response(raw_response),
                    "error": build_error_payload(e),
                    "curriculum_references": curriculum_references,
                    "image_reports": image_reports,
                    "usage": usage
                }

                last_error_payload = {
                    **build_error_payload(e),
                    "retry_reasons": [
                        "invalid_json"
                    ]
                }

                if model_index < len(models_to_try) - 1:
                    break

                return invalid_json_result

            except (ServerError, ClientError) as e:
                last_error_payload = build_error_payload(
                    e
                )

                wait_time = sleep_before_retry(
                    attempt,
                    error=e
                )

                progress.api_call_failed(
                    question_id=batch_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    error=last_error_payload,
                    wait_time=wait_time
                )

                reporter.log_attempt(
                    {
                        **attempt_payload,
                        "timestamp": datetime.now().isoformat(),
                        "status": "batch_api_error_retry",
                        "wait_time_seconds": wait_time,
                        "error": last_error_payload
                    }
                )

            except Exception as e:
                last_error_payload = build_error_payload(
                    e
                )

                wait_time = sleep_before_retry(
                    attempt,
                    error=e
                )

                progress.api_call_failed(
                    question_id=batch_id,
                    model_name=model_name,
                    attempt=attempt,
                    total_attempt=total_attempts_used,
                    error=last_error_payload,
                    wait_time=wait_time
                )

                reporter.log_attempt(
                    {
                        **attempt_payload,
                        "timestamp": datetime.now().isoformat(),
                        "status": "batch_unexpected_error_retry",
                        "wait_time_seconds": wait_time,
                        "error": last_error_payload
                    }
                )

        if model_index < len(models_to_try) - 1:
            next_model = models_to_try[
                model_index + 1
            ]

            progress.model_switch(
                question_id=batch_id,
                from_model=model_name,
                to_model=next_model,
                reason=(
                    f"Batch response validation failed: {', '.join(last_error_payload.get('retry_reasons', []))}."
                    if last_error_payload and last_error_payload.get("error_type") == "BatchResponseValidationError"
                    else "Batch failed after max retries."
                )
            )

            reporter.log_model_switch(
                {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "batch_id": batch_id,
                    "question_ids": question_ids,
                    "from_model": model_name,
                    "to_model": next_model,
                    "reason": (
                        f"Batch response validation failed: {', '.join(last_error_payload.get('retry_reasons', []))}."
                        if last_error_payload and last_error_payload.get("error_type") == "BatchResponseValidationError"
                        else "Batch failed after max retries."
                    ),
                    "last_error": last_error_payload
                }
            )

    return {
        "status": "batch_failed_after_all_models",
        "batch_id": batch_id,
        "question_ids": question_ids,
        "subject": subject,
        "model_name": last_model_name,
        "attempts_used": total_attempts_used,
        "error": last_error_payload,
        "curriculum_references": curriculum_references,
        "image_reports": last_image_reports,
        "usage": empty_usage()
    }


def build_batch_success_payload(
    reporter,
    record,
    batch_call,
    parsed_response,
    validation,
    usage,
    content_manifest
):
    question_id = get_batch_question_id(
        record
    )

    raw_result = json.dumps(
        {
            "questionId": question_id,
            **parsed_response
        },
        ensure_ascii=False
    )

    return {
        "timestamp": datetime.now().isoformat(),
        "run_id": reporter.run_id,
        "status": "success",
        "question_id": question_id,
        "subject": get_batch_subject(record),
        "question_type": get_record_question_type(record),
        "model_name": batch_call.get("model_name"),
        "model_attempt": None,
        "attempts_used": batch_call.get("attempts_used"),
        "prompt": get_record_prompt(record),
        "images": batch_call.get("image_reports", {}).get(question_id, []),
        "curriculum_references": batch_call.get("curriculum_references"),
        "raw_response": raw_result,
        "clean_response": raw_result,
        "parsed_response": parsed_response,
        "validation": validation,
        "content_manifest": content_manifest,
        "batch": {
            "batch_id": batch_call.get("batch_id")
        },
        "usage": usage
    }


def finalize_batch_failures(
    reporter,
    records,
    batch_call,
    usage_totals,
    content_manifests
):
    results = []
    status = batch_call.get(
        "status"
    )

    for record in records:
        question_id = get_batch_question_id(
            record
        )

        reconciliation = batch_call.get(
            "reconciliation",
            {}
        )
        invalid_detail = reconciliation.get(
            "invalid_results",
            {}
        ).get(
            question_id
        )

        payload = {
            "timestamp": datetime.now().isoformat(),
            "run_id": reporter.run_id,
            "status": (
                "skipped_api_call_limit_reached"
                if status == "batch_api_call_limit_reached"
                else
                "invalid_json_response"
                if status == "batch_invalid_json"
                else "failed_batch_validation"
                if status == "batch_response"
                else "failed_after_all_models"
            ),
            "question_id": question_id,
            "subject": get_batch_subject(record),
            "question_type": get_record_question_type(record),
            "model_name": batch_call.get("model_name"),
            "attempts_used": batch_call.get("attempts_used"),
            "prompt": get_record_prompt(record),
            "images": batch_call.get("image_reports", {}).get(question_id, []),
            "curriculum_references": batch_call.get("curriculum_references"),
            "content_manifest": content_manifests.get(question_id),
            "batch": {
                "batch_id": batch_call.get("batch_id"),
                "question_ids": batch_call.get("question_ids", [])
            },
            "validation": invalid_detail.get("validation") if invalid_detail else None,
            "error": batch_call.get("error") or {
                "error_type": "BatchResponseValidationError",
                "error_message": str(reconciliation.get("errors", [])),
                "error_repr": None
            },
            "raw_response": batch_call.get("raw_response", ""),
            "clean_response": batch_call.get("clean_response", ""),
            "usage": usage_totals.get(question_id, empty_usage())
        }

        if payload["status"] == "invalid_json_response":
            reporter.log_invalid_json(
                payload
            )
        elif payload["status"] == "skipped_api_call_limit_reached":
            reporter.log_skipped(
                payload
            )
        else:
            reporter.log_failure(
                payload
            )

        results.append(
            payload
        )

    return results


def process_batch_records(
    client,
    reporter,
    records,
    uploaded_files,
    progress,
    batch_id,
    content_manifests,
    batch_metadata=None,
    usage_totals=None,
    invalid_retry_count=0
):
    if is_run_stop_requested():
        return []

    usage_totals = usage_totals or {
        get_batch_question_id(record): empty_usage()
        for record in records
    }
    curriculum_file_keys = ()
    missing_curriculum_file_keys = ()

    if batch_metadata:
        group_key = batch_metadata.get(
            "group_key",
            ()
        )
        if len(group_key) > 4:
            curriculum_file_keys = group_key[4]
        if len(group_key) > 5:
            missing_curriculum_file_keys = group_key[5]

    batch_call = call_gemini_batch_with_model_switch(
        client=client,
        reporter=reporter,
        records=records,
        uploaded_files=uploaded_files,
        progress=progress,
        batch_id=batch_id,
        batch_metadata=batch_metadata
    )

    question_ids = [
        get_batch_question_id(record)
        for record in records
    ]

    allocated_usage = distribute_usage(
        batch_call.get("usage", {}),
        question_ids
    )

    for question_id in question_ids:
        usage_totals[question_id] = add_usage(
            usage_totals.get(question_id),
            allocated_usage.get(question_id)
        )

    if batch_call.get("status") in {
        "batch_api_call_limit_reached",
        "run_stop_requested"
    }:
        return finalize_batch_failures(
            reporter=reporter,
            records=records,
            batch_call=batch_call,
            usage_totals=usage_totals,
            content_manifests=content_manifests
        )

    if batch_call.get("status") == "batch_input_too_large":
        midpoint = len(records) // 2
        split_results = []

        for split_index, split_records in enumerate(
            [records[:midpoint], records[midpoint:]],
            start=1
        ):
            split_ids = [
                get_batch_question_id(record)
                for record in split_records
            ]

            split_results.extend(
                process_batch_records(
                    client=client,
                    reporter=reporter,
                    records=split_records,
                    uploaded_files=uploaded_files,
                    progress=progress,
                    batch_id=f"{batch_id}.token_split{split_index}",
                    content_manifests=content_manifests,
                    batch_metadata=build_batch_metadata_for_records(
                        records=split_records,
                        curriculum_file_keys=curriculum_file_keys,
                        missing_curriculum_file_keys=missing_curriculum_file_keys
                    ),
                    usage_totals={
                        question_id: usage_totals[question_id]
                        for question_id in split_ids
                    },
                    invalid_retry_count=0
                )
            )

        return split_results

    if batch_call.get("status") == "batch_response":
        reconciliation = batch_call.get(
            "reconciliation",
            {}
        )
        valid_results = reconciliation.get(
            "valid_results",
            {}
        )
        record_by_id = {
            get_batch_question_id(record): record
            for record in records
        }
        completed = []

        for question_id, result_detail in valid_results.items():
            payload = build_batch_success_payload(
                reporter=reporter,
                record=record_by_id[question_id],
                batch_call=batch_call,
                parsed_response=result_detail["parsed_response"],
                validation=result_detail["validation"],
                usage=usage_totals[question_id],
                content_manifest=content_manifests.get(question_id)
            )

            reporter.log_success(
                payload
            )
            completed.append(
                payload
            )

        pending_ids = (
            set(reconciliation.get("invalid_results", {}))
            | set(reconciliation.get("missing_ids", []))
        )
        pending_records = [
            record_by_id[question_id]
            for question_id in question_ids
            if question_id in pending_ids
        ]

        if not pending_records:
            return completed

        pending_usage = {
            question_id: usage_totals[question_id]
            for question_id in pending_ids
        }

        if (
            not completed
            and invalid_retry_count < BATCH_INVALID_JSON_RETRIES
        ):
            return process_batch_records(
                client=client,
                reporter=reporter,
                records=pending_records,
                uploaded_files=uploaded_files,
                progress=progress,
                batch_id=f"{batch_id}.retry{invalid_retry_count + 1}",
                content_manifests=content_manifests,
                batch_metadata=build_batch_metadata_for_records(
                    records=pending_records,
                    curriculum_file_keys=curriculum_file_keys,
                    missing_curriculum_file_keys=missing_curriculum_file_keys
                ),
                usage_totals=pending_usage,
                invalid_retry_count=invalid_retry_count + 1
            )

        if len(pending_records) == 1:
            if invalid_retry_count < BATCH_INVALID_JSON_RETRIES:
                retried = process_batch_records(
                    client=client,
                    reporter=reporter,
                    records=pending_records,
                    uploaded_files=uploaded_files,
                    progress=progress,
                    batch_id=f"{batch_id}.single_retry",
                    content_manifests=content_manifests,
                    batch_metadata=build_batch_metadata_for_records(
                        records=pending_records,
                        curriculum_file_keys=curriculum_file_keys,
                        missing_curriculum_file_keys=missing_curriculum_file_keys
                    ),
                    usage_totals=pending_usage,
                    invalid_retry_count=invalid_retry_count + 1
                )
                return [*completed, *retried]

            failed = finalize_batch_failures(
                reporter=reporter,
                records=pending_records,
                batch_call=batch_call,
                usage_totals=pending_usage,
                content_manifests=content_manifests
            )
            return [*completed, *failed]

        midpoint = len(pending_records) // 2
        split_results = []

        for split_index, split_records in enumerate(
            [
                pending_records[:midpoint],
                pending_records[midpoint:]
            ],
            start=1
        ):
            split_ids = [
                get_batch_question_id(record)
                for record in split_records
            ]
            split_usage = {
                question_id: pending_usage[question_id]
                for question_id in split_ids
            }

            split_results.extend(
                process_batch_records(
                    client=client,
                    reporter=reporter,
                    records=split_records,
                    uploaded_files=uploaded_files,
                    progress=progress,
                    batch_id=f"{batch_id}.split{split_index}",
                    content_manifests=content_manifests,
                    batch_metadata=build_batch_metadata_for_records(
                        records=split_records,
                        curriculum_file_keys=curriculum_file_keys,
                        missing_curriculum_file_keys=missing_curriculum_file_keys
                    ),
                    usage_totals=split_usage,
                    invalid_retry_count=0
                )
            )

        return [*completed, *split_results]

    if (
        batch_call.get("status") == "batch_invalid_json"
        and invalid_retry_count < BATCH_INVALID_JSON_RETRIES
    ):
        return process_batch_records(
            client=client,
            reporter=reporter,
            records=records,
            uploaded_files=uploaded_files,
            progress=progress,
            batch_id=f"{batch_id}.retry{invalid_retry_count + 1}",
            content_manifests=content_manifests,
            batch_metadata=batch_metadata,
            usage_totals=usage_totals,
            invalid_retry_count=invalid_retry_count + 1
        )

    if (
        batch_call.get("status") == "batch_invalid_json"
        and len(records) > 1
    ):
        midpoint = len(records) // 2
        split_results = []

        for split_index, split_records in enumerate(
            [records[:midpoint], records[midpoint:]],
            start=1
        ):
            split_ids = [
                get_batch_question_id(record)
                for record in split_records
            ]

            split_results.extend(
                process_batch_records(
                    client=client,
                    reporter=reporter,
                    records=split_records,
                    uploaded_files=uploaded_files,
                    progress=progress,
                    batch_id=f"{batch_id}.split{split_index}",
                    content_manifests=content_manifests,
                    batch_metadata=build_batch_metadata_for_records(
                        records=split_records,
                        curriculum_file_keys=curriculum_file_keys,
                        missing_curriculum_file_keys=missing_curriculum_file_keys
                    ),
                    usage_totals={
                        question_id: usage_totals[question_id]
                        for question_id in split_ids
                    },
                    invalid_retry_count=0
                )
            )

        return split_results

    return finalize_batch_failures(
        reporter=reporter,
        records=records,
        batch_call=batch_call,
        usage_totals=usage_totals,
        content_manifests=content_manifests
    )


def iter_prompt_preview_records(
    prompt_preview_root=None
):
    prompt_preview_root = Path(
        prompt_preview_root
        or PROMPT_PREVIEW_ROOT
    )

    if not prompt_preview_root.exists():
        raise FileNotFoundError(
            f"Prompt preview folder not found: {prompt_preview_root}"
        )

    for file_path in list_prompt_storage_files(
        prompt_preview_root
    ):
        data = load_json_file(
            file_path,
            default=[]
        )

        if isinstance(data, dict):
            data = (
                data.get("records")
                or data.get("data")
                or data.get("items")
                or []
            )

        if not isinstance(data, list):
            continue

        for record in data:
            if not isinstance(record, dict):
                continue

            record["_source_file"] = str(
                file_path
            )

            yield record


def load_previous_success_lookup(
    reports_root,
    exclude_run_id=None,
    enabled=True
):
    reports_root = Path(
        reports_root
    )

    summary = {
        "enabled": bool(enabled),
        "reports_root": str(reports_root),
        "excluded_run_id": exclude_run_id,
        "run_ids_scanned": [],
        "files_scanned": 0,
        "subject_counts": {},
        "total_success_question_ids": 0,
        "errors": []
    }

    if not enabled or not reports_root.exists():
        return {}, summary

    lookup = {}

    for run_dir in sorted(
        path for path in reports_root.iterdir()
        if path.is_dir()
    ):
        if exclude_run_id and run_dir.name == exclude_run_id:
            continue

        responses_root = (
            run_dir
            /
            "responses_by_subject"
        )

        if not responses_root.exists():
            continue

        summary["run_ids_scanned"].append(
            run_dir.name
        )

        for subject_dir in sorted(
            path for path in responses_root.iterdir()
            if path.is_dir()
        ):
            subject = normalize_subject_name(
                subject_dir.name
            )
            success_dir = (
                subject_dir
                /
                "success"
            )

            if not success_dir.exists():
                continue

            for success_file in sorted(
                success_dir.glob(
                    "*_success.json"
                )
            ):
                summary["files_scanned"] += 1

                try:
                    rows = load_json_file(
                        success_file,
                        default=[]
                    )
                except Exception as e:
                    summary["errors"].append(
                        {
                            "file": str(success_file),
                            "error": str(e)
                        }
                    )
                    continue

                if not isinstance(
                    rows,
                    list
                ):
                    summary["errors"].append(
                        {
                            "file": str(success_file),
                            "error": "Success report payload is not a JSON array."
                        }
                    )
                    continue

                subject_lookup = lookup.setdefault(
                    subject,
                    set()
                )

                for row in rows:
                    if not isinstance(
                        row,
                        dict
                    ):
                        continue

                    question_id = str(
                        row.get("question_id")
                        or ""
                    ).strip()

                    if not question_id:
                        continue

                    subject_lookup.add(
                        question_id
                    )

    summary["subject_counts"] = {
        subject: len(question_ids)
        for subject, question_ids in sorted(
            lookup.items()
        )
    }
    summary["total_success_question_ids"] = sum(
        summary["subject_counts"].values()
    )

    return lookup, summary


def select_records(
    process_limit=None,
    prompt_preview_root=None,
    excluded_subjects=(),
    previous_success_lookup=None
):
    selected_records = []
    skipped_subject_counts = {}
    skipped_previously_successful_counts = {}
    skipped_previously_successful_ids = {}
    excluded_subjects = {
        normalize_subject_name(
            subject
        )
        for subject in (excluded_subjects or ())
        if str(subject or "").strip()
    }
    previous_success_lookup = previous_success_lookup or {}

    for record in iter_prompt_preview_records(
        prompt_preview_root=prompt_preview_root
    ):
        subject = normalize_subject_name(
            get_record_subject(record)
        )
        question_id = get_record_question_id(
            record
        )

        if subject in excluded_subjects:
            skipped_subject_counts[subject] = skipped_subject_counts.get(
                subject,
                0
            ) + 1
            continue

        if question_id in previous_success_lookup.get(
            subject,
            set()
        ):
            skipped_previously_successful_counts[subject] = (
                skipped_previously_successful_counts.get(
                    subject,
                    0
                ) + 1
            )
            skipped_previously_successful_ids.setdefault(
                subject,
                []
            ).append(
                question_id
            )
            continue

        selected_records.append(
            record
        )

        if (
            process_limit is not None
            and process_limit > 0
            and
            len(selected_records) >= process_limit
        ):
            break

    return selected_records, {
        "excluded_subject_counts": skipped_subject_counts,
        "previous_success_counts": skipped_previously_successful_counts,
        "previous_success_question_ids": skipped_previously_successful_ids
    }


def main():
    load_dotenv()

    if BATCH_PREVIEW_ONLY and not BATCH_ENABLED:
        raise ValueError(
            "AI_ENGINE_BATCH_PREVIEW_ONLY requires AI_ENGINE_BATCH_ENABLED=true."
        )

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key and not BATCH_PREVIEW_ONLY:
        raise Exception(
            "GEMINI_API_KEY not found in .env file."
        )

    client = (
        genai.Client(api_key=api_key)
        if api_key
        else None
    )

    prompt_preview_root, prompt_preview_diagnostics = resolve_prompt_preview_root()

    uploaded_files = load_json_file(
        UPLOADED_FILES_PATH,
        default={}
    )

    reporter = GeminiUsageReporter(
        project_root=PROJECT_ROOT,
        run_name="gemini_classification",
        chunk_size=1000
    )

    previous_success_lookup, previous_success_lookup_summary = (
        load_previous_success_lookup(
            PROJECT_ROOT / "reports" / "gemini_runs",
            exclude_run_id=reporter.run_id,
            enabled=SKIP_PREVIOUS_SUCCESSES
        )
    )

    run_config = {
        "project_root": str(PROJECT_ROOT),
        "prompt_preview_root": str(prompt_preview_root),
        "prompt_preview_candidates": prompt_preview_diagnostics,
        "uploaded_files_path": str(UPLOADED_FILES_PATH),
        "process_limit": PROCESS_LIMIT,
        "skip_subjects": list(SKIP_SUBJECTS),
        "skip_previous_successes": SKIP_PREVIOUS_SUCCESSES,
        "previous_success_lookup_reports_root": str(
            PROJECT_ROOT / "reports" / "gemini_runs"
        ),
        "max_workers": MAX_WORKERS,
        "primary_model": PRIMARY_MODEL,
        "fallback_models": FALLBACK_MODELS,
        "max_retries_per_model": MAX_RETRIES_PER_MODEL,
        "retry_base_seconds": RETRY_BASE_SECONDS,
        "fail_schema_validation": FAIL_SCHEMA_VALIDATION,
        "api_limit_per_minute": TRIAL_API_LIMIT_PER_MINUTE,
        "api_limit_per_day": TRIAL_API_LIMIT_PER_DAY,
        "tokens_per_minute": TRIAL_TOKENS_PER_MINUTE,
        "use_remote_token_count": USE_REMOTE_TOKEN_COUNT,
        "batching": {
            "enabled": BATCH_ENABLED,
            "preview_only": BATCH_PREVIEW_ONLY,
            "max_questions": BATCH_MAX_QUESTIONS,
            "max_images": BATCH_MAX_IMAGES,
            "max_estimated_text_tokens": BATCH_MAX_ESTIMATED_TEXT_TOKENS,
            "max_actual_input_tokens": BATCH_MAX_INPUT_TOKENS,
            "invalid_json_retries_before_split": BATCH_INVALID_JSON_RETRIES,
            "single_question_fallback_available": True
        },
        "curriculum_rule": {
            "enabled_subjects": [
                "MATH",
                "MATH_EN",
                "SCIENCE",
                "SCIENCE_EN",
                "BIOLOGY",
                "BIOLOGY_EN",
                "CHEMISTRY",
                "CHEMISTRY_EN",
                "PHYSICS",
                "PHYSICS_EN"
            ],
            "grade_window": [
                "grade - 1",
                "grade",
                "grade + 1"
            ],
            "math_grade_gate": [
                5,
                8
            ]
        },
        "lesson_context": {
            "mode": os.getenv(
                "AI_ENGINE_LESSON_CONTEXT_MODE",
                "filtered_text"
            ),
            "max_section_texts": os.getenv(
                "AI_ENGINE_LESSON_MAX_SECTION_TEXTS",
                "40"
            ),
            "max_section_chars": os.getenv(
                "AI_ENGINE_LESSON_MAX_SECTION_CHARS",
                "8000"
            )
        },
        "response_storage": {
            "mode": "subject_wise_chunk_jsonl",
            "chunk_size": 1000
        }
    }

    reporter.save_run_config(
        run_config
    )

    reporter.write_json(
        reporter.report_root / "previous_success_lookup_summary.json",
        previous_success_lookup_summary
    )

    records, selection_metadata = select_records(
        process_limit=PROCESS_LIMIT,
        prompt_preview_root=prompt_preview_root,
        excluded_subjects=SKIP_SUBJECTS,
        previous_success_lookup=previous_success_lookup
    )

    reporter.write_json(
        reporter.report_root / "skipped_previously_successful_question_ids.json",
        selection_metadata.get(
            "previous_success_question_ids",
            {}
        )
    )

    reporter.summary["total_selected"] = len(
        records
    )
    reporter.summary["skipped_subjects"] = selection_metadata.get(
        "excluded_subject_counts",
        {}
    )
    reporter.summary["skipped_previously_successful"] = sum(
        int(value or 0)
        for value in selection_metadata.get(
            "previous_success_counts",
            {}
        ).values()
    )
    reporter.summary["skipped_previously_successful_by_subject"] = (
        selection_metadata.get(
            "previous_success_counts",
            {}
        )
    )

    content_manifest_rows = [
        build_content_manifest(record)
        for record in records
    ]

    id_counts = {}

    for manifest_row in content_manifest_rows:
        question_id = manifest_row.get(
            "question_id"
        )
        id_counts[question_id] = id_counts.get(
            question_id,
            0
        ) + 1

    for manifest_row in content_manifest_rows:
        question_id = manifest_row.get(
            "question_id"
        )

        if question_id and id_counts.get(question_id, 0) > 1:
            manifest_row["valid"] = False
            manifest_row["errors"].append(
                "duplicate_question_id_in_selected_input"
            )

    content_manifests = {
        row["question_id"]: row
        for row in content_manifest_rows
        if row.get("question_id")
    }

    missing_lo_id_rows = [
        {
            "question_id": row.get("question_id"),
            "subject": row.get("subject"),
            "grade": row.get("grade"),
            "question_type": row.get("question_type"),
            "reason": "question_id_not_present_in_filtered_questions_json"
        }
        for row in content_manifest_rows
        if row.get("question_id") and not row.get("lo_id_mapping_found")
    ]

    reporter.write_json(
        reporter.report_root / "question_content_manifest.json",
        content_manifest_rows
    )

    lesson_context_manifest_rows = build_lesson_context_manifest(
        records
    )

    reporter.write_json(
        reporter.report_root / "lesson_context_manifest.json",
        lesson_context_manifest_rows
    )

    reporter.write_json(
        reporter.report_root / "lesson_prompt_attachment_manifest.json",
        build_lesson_attachment_manifest(records)
    )

    reporter.write_json(
        reporter.report_root / "missing_filtered_question_mappings.json",
        missing_lo_id_rows
    )

    reporter.summary["missing_lo_id_mapping"] = len(
        missing_lo_id_rows
    )

    input_manifest = summarize_selected_records(
        records=records,
        prompt_preview_root=prompt_preview_root,
        prompt_preview_diagnostics=prompt_preview_diagnostics,
        selection_metadata=selection_metadata,
        previous_success_lookup_summary=previous_success_lookup_summary
    )

    reporter.write_json(
        reporter.report_root / "input_manifest.json",
        input_manifest
    )

    print_input_manifest(
        input_manifest
    )

    progress = ProgressPrinter(
        total_records=len(records)
    )

    RUN_STATE["progress"] = progress
    RUN_STATE["reporter"] = reporter

    progress.print_run_start(
        run_id=reporter.run_id,
        process_limit=PROCESS_LIMIT,
        max_workers=MAX_WORKERS,
        primary_model=PRIMARY_MODEL,
        fallback_models=FALLBACK_MODELS
    )

    if not records:
        print(
            "\nNo records found to process.",
            flush=True
        )

        summary = reporter.save_summary()

        print(
            json.dumps(
                summary,
                indent=4,
                ensure_ascii=False
            ),
            flush=True
        )

        return

    valid_records = []

    for record, manifest_row in zip(
        records,
        content_manifest_rows
    ):
        if manifest_row.get("valid"):
            valid_records.append(
                record
            )
            continue

        failure_payload = {
            "timestamp": datetime.now().isoformat(),
            "run_id": reporter.run_id,
            "status": "failed_input_content_validation",
            "question_id": get_batch_question_id(record) or "unknown_question_id",
            "subject": get_batch_subject(record),
            "question_type": get_record_question_type(record),
            "model_name": None,
            "attempts_used": 0,
            "prompt": get_record_prompt(record),
            "images": get_record_images(record),
            "curriculum_references": None,
            "content_manifest": manifest_row,
            "error": {
                "error_type": "InputContentValidationError",
                "error_message": str(manifest_row.get("errors", [])),
                "error_repr": None
            },
            "usage": empty_usage()
        }

        reporter.log_failure(
            failure_payload
        )
        progress.record_done(
            failure_payload
        )

    if BATCH_ENABLED:
        batches = build_batches(
            records=valid_records,
            uploaded_files=uploaded_files,
            max_questions=max(1, BATCH_MAX_QUESTIONS),
            max_images=max(1, BATCH_MAX_IMAGES),
            max_estimated_text_tokens=max(1, BATCH_MAX_ESTIMATED_TEXT_TOKENS)
        )

        reporter.summary["batches_created"] = len(
            batches
        )
        reporter.summary["batching_enabled"] = True

        batch_manifest_rows = []

        for batch_number, batch in enumerate(
            batches,
            start=1
        ):
            group_key = batch["group_key"]
            batch_manifest_rows.append(
                {
                    "batch_id": f"batch_{batch_number:06d}",
                    "lo_id": group_key[0],
                    "subject": group_key[1],
                    "grade": group_key[2],
                    "course_code": group_key[3],
                    "curriculum_file_keys": list(group_key[4]),
                    "missing_curriculum_file_keys": list(group_key[5]),
                    "question_count": len(batch["records"]),
                    "question_ids": [
                        get_batch_question_id(record)
                        for record in batch["records"]
                    ],
                    "estimated_text_tokens": batch["estimated_text_tokens"],
                    "image_count": batch["image_count"]
                }
            )

        reporter.write_json(
            reporter.report_root / "batch_manifest.json",
            batch_manifest_rows
        )

        reporter.write_json(
            reporter.report_root / "batch_lesson_attachment_manifest.json",
            build_batch_lesson_attachment_manifest(batches)
        )

        if BATCH_PREVIEW_ONLY:
            preview_batch_items = list(
                enumerate(
                    batches,
                    start=1
                )
            )

            if PREFLIGHT_BILLING_ENABLED:
                pre_run_billing_estimate = build_pre_run_billing_estimate(
                    reporter=reporter,
                    client=client,
                    uploaded_files=uploaded_files,
                    valid_records=[],
                    runnable_batches=preview_batch_items
                )
                print_pre_run_billing_estimate(
                    pre_run_billing_estimate
                )

            reporter.write_json(
                reporter.report_root / "billing_summary.json",
                {
                    "preview_only": True,
                    "generated_at": datetime.now().isoformat(),
                    "estimated_prompt_tokens": 0,
                    "actual_input_tokens": 0,
                    "output_tokens": 0,
                    "thinking_tokens": 0,
                    "billable_output_tokens": 0,
                    "cached_tokens": 0,
                    "total_tokens": 0,
                    "expected_billing_usd": 0.0,
                    "billing_breakdown_usd": {
                        "input": 0.0,
                        "output_including_thinking": 0.0,
                        "cache": 0.0
                    },
                    "by_model": {},
                    "unpriced_models": []
                }
            )

            write_assembled_request_previews(
                reporter,
                batches
            )
            reporter.summary["preview_only"] = True
            summary = reporter.save_summary()

            print(
                "\nBatch preview complete. No Gemini generation calls were made.",
                flush=True
            )
            print(
                f"Content manifest: {reporter.report_root / 'question_content_manifest.json'}",
                flush=True
            )
            print(
                f"Batch manifest  : {reporter.report_root / 'batch_manifest.json'}",
                flush=True
            )
            print(
                json.dumps(summary, indent=4, ensure_ascii=False),
                flush=True
            )
            return

        runnable_batches = []

        for batch_number, batch in enumerate(
            batches,
            start=1
        ):
            resolved_curriculum_keys = batch["group_key"][4]
            missing_curriculum_keys = batch["group_key"][5]

            if resolved_curriculum_keys or not missing_curriculum_keys:
                runnable_batches.append(
                    (batch_number, batch)
                )
                continue

            for record in batch["records"]:
                question_id = get_batch_question_id(
                    record
                )
                failure_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": reporter.run_id,
                    "status": "failed_curriculum_files_missing",
                    "question_id": question_id,
                    "subject": get_batch_subject(record),
                    "question_type": get_record_question_type(record),
                    "model_name": None,
                    "attempts_used": 0,
                    "prompt": get_record_prompt(record),
                    "images": get_record_images(record),
                    "curriculum_references": {
                        "missing_file_keys": list(missing_curriculum_keys)
                    },
                    "content_manifest": content_manifests.get(question_id),
                    "error": {
                        "error_type": "CurriculumFilesMissing",
                        "error_message": str(list(missing_curriculum_keys)),
                        "error_repr": None
                    },
                    "usage": empty_usage()
                }

                reporter.log_failure(
                    failure_payload
                )
                progress.record_done(
                    failure_payload
                )

        if PREFLIGHT_BILLING_ENABLED:
            pre_run_billing_estimate = build_pre_run_billing_estimate(
                reporter=reporter,
                client=client,
                uploaded_files=uploaded_files,
                valid_records=[],
                runnable_batches=runnable_batches
            )
            print_pre_run_billing_estimate(
                pre_run_billing_estimate
            )

        if max(1, MAX_WORKERS) == 1:
            for batch_number, batch in runnable_batches:
                if is_run_stop_requested():
                    break

                batch_id = f"batch_{batch_number:06d}"

                try:
                    results = process_batch_records(
                        client,
                        reporter,
                        batch["records"],
                        uploaded_files,
                        progress,
                        batch_id,
                        content_manifests,
                        batch
                    )

                    for result in results:
                        progress.record_done(
                            result
                        )

                except Exception as e:
                    progress.worker_crashed(
                        e,
                        record_count=len(batch["records"])
                    )

                    print(
                        traceback.format_exc(),
                        flush=True
                    )
        else:
            with ThreadPoolExecutor(
                max_workers=max(1, MAX_WORKERS)
            ) as executor:
                futures = {}

                for batch_number, batch in runnable_batches:
                    if is_run_stop_requested():
                        break

                    batch_id = f"batch_{batch_number:06d}"
                    future = executor.submit(
                        process_batch_records,
                        client,
                        reporter,
                        batch["records"],
                        uploaded_files,
                        progress,
                        batch_id,
                        content_manifests,
                        batch
                    )
                    futures[future] = batch

                for future in as_completed(
                    futures
                ):
                    try:
                        results = future.result()

                        for result in results:
                            progress.record_done(
                                result
                            )

                    except Exception as e:
                        progress.worker_crashed(
                            e,
                            record_count=len(futures[future]["records"])
                        )

                        print(
                            traceback.format_exc(),
                            flush=True
                        )
    else:
        reporter.summary["batching_enabled"] = False

        if PREFLIGHT_BILLING_ENABLED:
            pre_run_billing_estimate = build_pre_run_billing_estimate(
                reporter=reporter,
                client=client,
                uploaded_files=uploaded_files,
                valid_records=valid_records,
                runnable_batches=[]
            )
            print_pre_run_billing_estimate(
                pre_run_billing_estimate
            )

        if max(1, MAX_WORKERS) == 1:
            for record in valid_records:
                if is_run_stop_requested():
                    break

                try:
                    result = call_gemini_with_model_switch(
                        client,
                        reporter,
                        record,
                        uploaded_files,
                        progress
                    )
                    progress.record_done(
                        result
                    )

                except Exception as e:
                    progress.worker_crashed(
                        e
                    )

                    print(
                        traceback.format_exc(),
                        flush=True
                    )
        else:
            with ThreadPoolExecutor(
                max_workers=max(1, MAX_WORKERS)
            ) as executor:
                futures = {}

                for record in valid_records:
                    if is_run_stop_requested():
                        break

                    future = executor.submit(
                        call_gemini_with_model_switch,
                        client,
                        reporter,
                        record,
                        uploaded_files,
                        progress
                    )
                    futures[future] = record

                for future in as_completed(
                    futures
                ):
                    try:
                        result = future.result()
                        progress.record_done(
                            result
                        )

                    except Exception as e:
                        progress.worker_crashed(
                            e
                        )

                        print(
                            traceback.format_exc(),
                            flush=True
                        )

    summary = reporter.save_summary()
    final_execution_report = reporter.build_final_execution_report(
        summary
    )
    billing_summary = build_billing_summary(
        summary,
        final_execution_report
    )
    reporter.write_json(
        reporter.report_root / "billing_summary.json",
        billing_summary
    )

    if is_run_stop_requested():
        print(
            f"\nRUN STOPPED EARLY: {RUN_STATE.get('stop_reason')}",
            flush=True
        )

    print(
        "\n========== RUN SUMMARY ==========",
        flush=True
    )

    print(
        json.dumps(
            summary,
            indent=4,
            ensure_ascii=False
        ),
        flush=True
    )

    print_billing_summary(
        billing_summary
    )

    print(
        f"\nReports stored at:\n{reporter.report_root}",
        flush=True
    )

    print(
        f"\nGlobal usage ledger:\n{reporter.global_usage_file}",
        flush=True
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        progress = RUN_STATE.get("progress")
        reporter = RUN_STATE.get("reporter")

        if progress:
            progress.print_interrupt_summary(
                reason="KeyboardInterrupt"
            )

        if reporter:
            summary = reporter.save_summary()
            print(
                json.dumps(
                    summary,
                    indent=4,
                    ensure_ascii=False
                ),
                flush=True
            )

        print(
            "Interrupted by user.",
            flush=True
        )
