import json
import copy
import threading
from pathlib import Path
from datetime import datetime


class GeminiUsageReporter:
    def __init__(
        self,
        project_root,
        run_id=None,
        run_name="gemini_classification",
        chunk_size=1000
    ):
        self.project_root = Path(
            project_root
        )

        self.run_id = (
            run_id
            or datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        self.run_name = run_name

        self.started_at = datetime.now().isoformat()

        self.chunk_size = chunk_size

        self.report_root = (
            self.project_root
            /
            "reports"
            /
            "gemini_runs"
            /
            self.run_id
        )

        self.response_chunk_root = (
            self.report_root
            /
            "responses_by_subject"
        )

        # Global file for all runs.
        # JSON array format, not JSONL.
        self.global_usage_file = (
            self.project_root
            /
            "reports"
            /
            "gemini_usage_all_runs.json"
        )

        self.lock = threading.RLock()

        self.subject_chunk_state = {}

        self.summary = {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "started_at": self.started_at,
            "ended_at": None,
            "chunk_size": self.chunk_size,

            "total_selected": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "invalid_json": 0,
            "skipped": 0,

            "total_attempts": 0,
            "model_switches": 0,

            "text_only": 0,
            "image_only": 0,
            "text_plus_image": 0,
            "no_content": 0,

            "estimated_prompt_tokens": 0,
            "preflight_estimated_prompt_tokens_total": 0,
            "preflight_generation_calls": 0,
            "actual_prompt_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0
        }

        self._create_dirs()

    def _create_dirs(
        self
    ):
        folders = [
            self.report_root,
            self.response_chunk_root,
            self.global_usage_file.parent
        ]

        for folder in folders:
            folder.mkdir(
                parents=True,
                exist_ok=True
            )

    def safe_file_name(
        self,
        value
    ):
        value = str(
            value or "UNKNOWN"
        )

        safe = "".join(
            char
            if char.isalnum() or char in ["-", "_", "."]
            else "_"
            for char in value
        )

        return safe[:180]

    def normalize_subject(
        self,
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

    def write_json(
        self,
        file_path,
        payload
    ):
        file_path = Path(
            file_path
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                payload,
                f,
                indent=4,
                ensure_ascii=False,
                default=str
            )

    def read_json(
        self,
        file_path,
        default
    ):
        file_path = Path(
            file_path
        )

        if not file_path.exists():
            return default

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:
                return json.load(
                    f
                )

        except Exception:
            return default

    def make_json_safe(
        self,
        value
    ):
        if isinstance(
            value,
            dict
        ):
            return {
                str(key): self.make_json_safe(item)
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple, set)
        ):
            return [
                self.make_json_safe(item)
                for item in value
            ]

        if isinstance(
            value,
            Path
        ):
            return str(
                value
            )

        if isinstance(
            value,
            datetime
        ):
            return value.isoformat()

        return value

    def append_json_array(
        self,
        file_path,
        payload
    ):
        """
        Store data in normal JSON array format.

        Example:
        [
            {...},
            {...}
        ]
        """

        file_path = Path(
            file_path
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        data = self.read_json(
            file_path,
            default=[]
        )

        if not isinstance(
            data,
            list
        ):
            data = []

        data.append(
            payload
        )

        self.write_json(
            file_path,
            data
        )

    def _safe_divide(
        self,
        numerator,
        denominator,
        digits=6
    ):
        if not denominator:
            return None

        return round(
            numerator / denominator,
            digits
        )

    def _read_array_file(
        self,
        file_path
    ):
        payload = self.read_json(
            file_path,
            default=[]
        )

        return payload if isinstance(payload, list) else []

    def _subject_report_payload(
        self,
        subject
    ):
        subject = self.normalize_subject(
            subject
        )

        subject_dir = self.get_subject_dir(
            subject
        )
        chunk_records = []

        for category in ["success", "failed"]:
            category_dir = self.get_subject_dir(
                subject,
                category=category
            )

            for chunk_file in sorted(
                category_dir.glob(
                    f"{self.safe_file_name(subject)}_chunk_*.json"
                )
            ):
                chunk_records.extend(
                    self._read_array_file(
                        chunk_file
                    )
                )

        return {
            "success": self._read_array_file(
                self.get_subject_report_file(
                    subject,
                    "success",
                    category="success"
                )
            ),
            "failures": self._read_array_file(
                self.get_subject_report_file(
                    subject,
                    "failures",
                    category="failed"
                )
            ),
            "invalid_json": self._read_array_file(
                self.get_subject_report_file(
                    subject,
                    "invalid_json",
                    category="failed"
                )
            ),
            "skipped": self._read_array_file(
                self.get_subject_report_file(
                    subject,
                    "skipped",
                    category="failed"
                )
            ),
            "records": chunk_records
        }

    def build_report_index(
        self
    ):
        return {
            "run_config": str(
                self.report_root / "run_config.json"
            ),
            "input_manifest": str(
                self.report_root / "input_manifest.json"
            ),
            "attempts": str(
                self.report_root / "attempts.json"
            ),
            "preflight_token_usage": str(
                self.report_root / "preflight_token_usage.json"
            ),
            "preflight_token_usage_summary": str(
                self.report_root / "preflight_token_usage_summary.json"
            ),
            "pre_run_billing_estimate": str(
                self.report_root / "pre_run_billing_estimate.json"
            ),
            "billing_summary": str(
                self.report_root / "billing_summary.json"
            ),
            "model_switches": str(
                self.report_root / "model_switches.json"
            ),
            "run_summary": str(
                self.report_root / "run_summary.json"
            ),
            "completed_question_ids": str(
                self.report_root / "completed_question_ids.txt"
            ),
            "failed_question_ids": str(
                self.report_root / "failed_question_ids.txt"
            ),
            "responses_by_subject": str(
                self.response_chunk_root
            ),
            "final_execution_report_json": str(
                self.report_root / "final_execution_report.json"
            ),
            "final_execution_report_txt": str(
                self.report_root / "final_execution_report.txt"
            ),
            "global_usage_file": str(
                self.global_usage_file
            )
        }

    def build_summary_metrics(
        self
    ):
        processed = int(
            self.summary.get("processed")
            or 0
        )

        success = int(
            self.summary.get("success")
            or 0
        )

        failed = int(
            self.summary.get("failed")
            or 0
        )

        total_tokens = int(
            self.summary.get("total_tokens")
            or 0
        )

        output_tokens = int(
            self.summary.get("output_tokens")
            or 0
        )

        actual_prompt_tokens = int(
            self.summary.get("actual_prompt_tokens")
            or 0
        )

        started_at = datetime.fromisoformat(
            self.started_at
        )

        ended_at = datetime.now()

        duration_seconds = (
            ended_at
            -
            started_at
        ).total_seconds()

        return {
            "duration_seconds": round(
                duration_seconds,
                3
            ),
            "records_per_second": (
                round(
                    processed / duration_seconds,
                    6
                )
                if duration_seconds > 0
                else None
            ),
            "success_rate": (
                round(
                    success / processed,
                    6
                )
                if processed
                else None
            ),
            "failure_rate": (
                round(
                    failed / processed,
                    6
                )
                if processed
                else None
            ),
            "average_total_tokens_per_processed_record": (
                round(
                    total_tokens / processed,
                    3
                )
                if processed
                else None
            ),
            "average_prompt_tokens_per_success": (
                round(
                    actual_prompt_tokens / success,
                    3
                )
                if success
                else None
            ),
            "average_output_tokens_per_success": (
                round(
                    output_tokens / success,
                    3
                )
                if success
                else None
            )
        }

    def append_text_line(
        self,
        file_path,
        text
    ):
        file_path = Path(
            file_path
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            file_path,
            "a",
            encoding="utf-8"
        ) as f:
            f.write(
                str(text)
                +
                "\n"
            )

    def remove_prompt_fields(
        self,
        payload
    ):
        """
        Prompt is used only for Gemini request.
        We do not store prompt in report files.
        """

        clean_payload = copy.deepcopy(
            payload
        )

        keys_to_remove = [
            "prompt",
            "gemini_prompt"
        ]

        for key in keys_to_remove:
            clean_payload.pop(
                key,
                None
            )

        return clean_payload

    def get_content_mode(
        self,
        prompt,
        images
    ):
        has_text = bool(
            str(prompt or "").strip()
        )

        has_images = bool(
            images
        )

        if has_text and has_images:
            return "text_plus_image"

        if has_text and not has_images:
            return "text_only"

        if not has_text and has_images:
            return "image_only"

        return "no_content"

    def get_subject_dir(
        self,
        subject,
        category=None
    ):
        subject = self.normalize_subject(
            subject
        )

        subject_folder = self.safe_file_name(
            subject
        )

        subject_dir = (
            self.response_chunk_root
            /
            subject_folder
        )

        if category:
            subject_dir = (
                subject_dir
                /
                self.safe_file_name(category)
            )

        subject_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        return subject_dir

    def get_subject_report_file(
        self,
        subject,
        file_name,
        category=None
    ):
        """
        Returns subject-wise JSON report file.

        Example:
        responses_by_subject/MATH/MATH_success.json
        responses_by_subject/SCIENCE/SCIENCE_failures.json
        """

        subject = self.normalize_subject(
            subject
        )

        subject_folder = self.safe_file_name(
            subject
        )

        subject_dir = self.get_subject_dir(
            subject,
            category=category
        )

        return (
            subject_dir
            /
            f"{subject_folder}_{file_name}.json"
        )

    def save_run_config(
        self,
        config
    ):
        payload = {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "started_at": self.started_at,
            "chunk_size": self.chunk_size,
            "config": config
        }

        with self.lock:
            self.write_json(
                self.report_root / "run_config.json",
                payload
            )

    def _get_subject_chunk_state(
        self,
        subject,
        category
    ):
        subject = self.normalize_subject(
            subject
        )
        state_key = (
            subject,
            str(category or "default")
        )

        if state_key not in self.subject_chunk_state:
            self.subject_chunk_state[state_key] = {
                "chunk_number": 1,
                "records_in_current_chunk": 0
            }

        return self.subject_chunk_state[state_key]

    def _get_current_chunk_file(
        self,
        subject,
        category
    ):
        subject = self.normalize_subject(
            subject
        )

        state = self._get_subject_chunk_state(
            subject,
            category
        )

        subject_folder = self.safe_file_name(
            subject
        )

        subject_dir = self.get_subject_dir(
            subject,
            category=category
        )

        return (
            subject_dir
            /
            f"{subject_folder}_chunk_{state['chunk_number']:06d}.json"
        )

    def _write_complete_response_to_subject_chunk(
        self,
        payload,
        category
    ):
        """
        Writes complete Gemini response into subject-wise chunk JSON file.

        Example:
        responses_by_subject/
          MATH/
            success/MATH_chunk_000001.json

        Each chunk file is a JSON array.
        """

        subject = self.normalize_subject(
            payload.get("subject")
        )

        state = self._get_subject_chunk_state(
            subject,
            category
        )

        if (
            state["records_in_current_chunk"]
            >=
            self.chunk_size
        ):
            state["chunk_number"] += 1
            state["records_in_current_chunk"] = 0

        chunk_file = self._get_current_chunk_file(
            subject,
            category
        )

        payload["response_chunk_file"] = str(
            chunk_file
        )

        clean_payload = self.remove_prompt_fields(
            payload
        )

        self.append_json_array(
            chunk_file,
            clean_payload
        )

        state["records_in_current_chunk"] += 1

        return str(
            chunk_file
        )

    def _build_light_report_payload(
        self,
        payload
    ):
        return {
            "timestamp": payload.get("timestamp"),
            "run_id": payload.get("run_id"),
            "status": payload.get("status"),
            "question_id": payload.get("question_id"),
            "subject": payload.get("subject"),
            "question_type": payload.get("question_type"),
            "model_name": payload.get("model_name"),
            "model_attempt": payload.get("model_attempt"),
            "attempts_used": payload.get("attempts_used"),
            "content_mode": payload.get("content_mode"),
            "image_count": len(payload.get("images", []) or []),
            "response_chunk_file": payload.get("response_chunk_file"),
            "usage": payload.get("usage", {}),
            "validation": payload.get("validation"),
            "error": payload.get("error")
        }

    def _build_usage_payload(
        self,
        payload,
        status,
        content_mode,
        images,
        chunk_file
    ):
        return {
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "question_id": payload.get("question_id"),
            "subject": payload.get("subject"),
            "question_type": payload.get("question_type"),
            "model_name": payload.get("model_name"),
            "status": status,
            "attempts_used": payload.get("attempts_used"),
            "content_mode": content_mode,
            "image_count": len(images or []),
            "response_chunk_file": chunk_file,
            "error": payload.get("error"),
            "usage": payload.get("usage", {})
        }

    def _add_usage_to_summary(
        self,
        usage
    ):
        usage = usage or {}

        self.summary["estimated_prompt_tokens"] += int(
            usage.get("estimated_prompt_tokens") or 0
        )
        self.summary["actual_prompt_tokens"] += int(
            usage.get("prompt_token_count") or 0
        )
        self.summary["output_tokens"] += int(
            usage.get("candidates_token_count") or 0
        )
        self.summary["thinking_tokens"] += int(
            usage.get("thoughts_token_count") or 0
        )
        self.summary["cached_tokens"] += int(
            usage.get("cached_content_token_count") or 0
        )
        self.summary["total_tokens"] += int(
            usage.get("total_token_count") or 0
        )

    def log_attempt(
        self,
        payload
    ):
        with self.lock:
            self.summary["total_attempts"] += 1

            clean_payload = self.remove_prompt_fields(
                payload
            )

            # Run-level log
            self.append_json_array(
                self.report_root / "attempts.json",
                clean_payload
            )

    def log_preflight_token_usage(
        self,
        payload
    ):
        with self.lock:
            estimated_prompt_tokens = int(
                payload.get("estimated_prompt_tokens") or 0
            )

            self.summary["preflight_generation_calls"] += 1
            self.summary["preflight_estimated_prompt_tokens_total"] += (
                estimated_prompt_tokens
            )

            self.append_json_array(
                self.report_root / "preflight_token_usage.json",
                self.remove_prompt_fields(
                    payload
                )
            )

    def build_preflight_token_usage_summary(
        self
    ):
        rows = self.read_json(
            self.report_root / "preflight_token_usage.json",
            default=[]
        )

        if not isinstance(
            rows,
            list
        ):
            rows = []

        by_model = {}
        by_mode = {}

        for row in rows:
            if not isinstance(
                row,
                dict
            ):
                continue

            model_name = str(
                row.get("model_name") or "UNKNOWN"
            )
            mode = str(
                row.get("request_mode") or "unknown"
            )
            estimated_prompt_tokens = int(
                row.get("estimated_prompt_tokens") or 0
            )

            if model_name not in by_model:
                by_model[model_name] = {
                    "calls": 0,
                    "estimated_prompt_tokens": 0
                }

            by_model[model_name]["calls"] += 1
            by_model[model_name]["estimated_prompt_tokens"] += (
                estimated_prompt_tokens
            )

            if mode not in by_mode:
                by_mode[mode] = {
                    "calls": 0,
                    "estimated_prompt_tokens": 0
                }

            by_mode[mode]["calls"] += 1
            by_mode[mode]["estimated_prompt_tokens"] += (
                estimated_prompt_tokens
            )

        return {
            "run_id": self.run_id,
            "generated_at": datetime.now().isoformat(),
            "total_preflight_generation_calls": self.summary.get(
                "preflight_generation_calls",
                0
            ),
            "total_estimated_prompt_tokens_before_generate_content": self.summary.get(
                "preflight_estimated_prompt_tokens_total",
                0
            ),
            "by_model": by_model,
            "by_request_mode": by_mode
        }

    def log_model_switch(
        self,
        payload
    ):
        with self.lock:
            self.summary["model_switches"] += 1

            clean_payload = self.remove_prompt_fields(
                payload
            )

            # Run-level log
            self.append_json_array(
                self.report_root / "model_switches.json",
                clean_payload
            )

    def log_success(
        self,
        payload
    ):
        with self.lock:
            question_id = payload.get(
                "question_id"
            )

            subject = self.normalize_subject(
                payload.get("subject")
            )

            prompt = payload.get(
                "prompt"
            )

            images = payload.get(
                "images",
                []
            )

            usage = payload.get(
                "usage",
                {}
            )

            content_mode = self.get_content_mode(
                prompt,
                images
            )

            payload["subject"] = subject
            payload["content_mode"] = content_mode
            payload["stored_as"] = "subject_wise_json"
            payload["response_chunk_file"] = None

            chunk_file = self._write_complete_response_to_subject_chunk(
                payload,
                category="success"
            )

            payload["response_chunk_file"] = chunk_file

            self.summary["processed"] += 1
            self.summary["success"] += 1
            self.summary[content_mode] += 1

            self._add_usage_to_summary(
                usage
            )

            light_payload = self._build_light_report_payload(
                payload
            )

            # Subject-wise files
            self.append_json_array(
                self.get_subject_report_file(
                    subject,
                    "success",
                    category="success"
                ),
                light_payload
            )

            usage_payload = self._build_usage_payload(
                payload=payload,
                status="success",
                content_mode=content_mode,
                images=images,
                chunk_file=chunk_file
            )

            # Global usage
            self.append_json_array(
                self.global_usage_file,
                usage_payload
            )

            # Run-level completed IDs
            self.append_text_line(
                self.report_root / "completed_question_ids.txt",
                question_id
            )

    def log_failure(
        self,
        payload
    ):
        with self.lock:
            question_id = payload.get(
                "question_id"
            )

            subject = self.normalize_subject(
                payload.get("subject")
            )

            prompt = payload.get(
                "prompt"
            )

            images = payload.get(
                "images",
                []
            )

            content_mode = self.get_content_mode(
                prompt,
                images
            )

            payload["subject"] = subject
            payload["content_mode"] = content_mode
            payload["stored_as"] = "subject_wise_json"
            payload["response_chunk_file"] = None

            chunk_file = self._write_complete_response_to_subject_chunk(
                payload,
                category="failed"
            )

            payload["response_chunk_file"] = chunk_file

            self.summary["processed"] += 1
            self.summary["failed"] += 1
            self.summary[content_mode] += 1

            self._add_usage_to_summary(
                payload.get("usage", {})
            )

            light_payload = self._build_light_report_payload(
                payload
            )

            usage_payload = self._build_usage_payload(
                payload=payload,
                status=payload.get("status", "failed"),
                content_mode=content_mode,
                images=images,
                chunk_file=chunk_file
            )

            # Subject-wise file
            self.append_json_array(
                self.get_subject_report_file(
                    subject,
                    "failures",
                    category="failed"
                ),
                light_payload
            )

            # Global usage
            self.append_json_array(
                self.global_usage_file,
                usage_payload
            )

            # Run-level failed IDs
            self.append_text_line(
                self.report_root / "failed_question_ids.txt",
                question_id
            )

    def log_invalid_json(
        self,
        payload
    ):
        with self.lock:
            question_id = payload.get(
                "question_id"
            )

            subject = self.normalize_subject(
                payload.get("subject")
            )

            prompt = payload.get(
                "prompt"
            )

            images = payload.get(
                "images",
                []
            )

            content_mode = self.get_content_mode(
                prompt,
                images
            )

            payload["subject"] = subject
            payload["content_mode"] = content_mode
            payload["stored_as"] = "subject_wise_json"
            payload["response_chunk_file"] = None

            chunk_file = self._write_complete_response_to_subject_chunk(
                payload,
                category="failed"
            )

            payload["response_chunk_file"] = chunk_file

            self.summary["processed"] += 1
            self.summary["invalid_json"] += 1
            self.summary["failed"] += 1
            self.summary[content_mode] += 1

            self._add_usage_to_summary(
                payload.get("usage", {})
            )

            light_payload = self._build_light_report_payload(
                payload
            )

            usage_payload = self._build_usage_payload(
                payload=payload,
                status="invalid_json_response",
                content_mode=content_mode,
                images=images,
                chunk_file=chunk_file
            )

            # Subject-wise file
            self.append_json_array(
                self.get_subject_report_file(
                    subject,
                    "invalid_json",
                    category="failed"
                ),
                light_payload
            )

            # Global usage
            self.append_json_array(
                self.global_usage_file,
                usage_payload
            )

            # Run-level failed IDs
            self.append_text_line(
                self.report_root / "failed_question_ids.txt",
                question_id
            )

    def log_skipped(
        self,
        payload
    ):
        with self.lock:
            question_id = payload.get(
                "question_id"
            )

            subject = self.normalize_subject(
                payload.get("subject")
            )

            prompt = payload.get(
                "prompt"
            )

            images = payload.get(
                "images",
                []
            )

            content_mode = self.get_content_mode(
                prompt,
                images
            )

            payload["subject"] = subject
            payload["content_mode"] = content_mode
            payload["stored_as"] = "subject_wise_json"
            payload["response_chunk_file"] = None

            chunk_file = self._write_complete_response_to_subject_chunk(
                payload,
                category="failed"
            )

            payload["response_chunk_file"] = chunk_file

            self.summary["processed"] += 1
            self.summary["skipped"] += 1
            self.summary[content_mode] += 1

            light_payload = self._build_light_report_payload(
                payload
            )

            global_payload = {
                "timestamp": datetime.now().isoformat(),
                "run_id": self.run_id,
                "question_id": question_id,
                "subject": subject,
                "status": "skipped",
                "content_mode": content_mode,
                "response_chunk_file": chunk_file,
                "reason": payload.get("reason")
            }

            # Subject-wise file
            self.append_json_array(
                self.get_subject_report_file(
                    subject,
                    "skipped",
                    category="failed"
                ),
                light_payload
            )

            # Global usage
            self.append_json_array(
                self.global_usage_file,
                global_payload
            )

    def _build_subject_execution_summary(
        self
    ):
        summary = {}

        if not self.response_chunk_root.exists():
            return summary

        for subject_dir in sorted(
            path for path in self.response_chunk_root.iterdir()
            if path.is_dir()
        ):
            subject = self.normalize_subject(
                subject_dir.name
            )
            payload = self._subject_report_payload(
                subject
            )

            processed = (
                len(payload["success"])
                + len(payload["failures"])
                + len(payload["invalid_json"])
                + len(payload["skipped"])
            )
            total_tokens = sum(
                int(
                    (item.get("usage") or {}).get("total_token_count") or 0
                )
                for item in payload["records"]
            )
            prompt_tokens = sum(
                int(
                    (item.get("usage") or {}).get("prompt_token_count") or 0
                )
                for item in payload["records"]
            )
            output_tokens = sum(
                int(
                    (item.get("usage") or {}).get("candidates_token_count") or 0
                )
                for item in payload["records"]
            )

            summary[subject] = {
                "processed": processed,
                "success": len(payload["success"]),
                "failures": len(payload["failures"]),
                "invalid_json": len(payload["invalid_json"]),
                "skipped": len(payload["skipped"]),
                "success_rate": self._safe_divide(
                    len(payload["success"]),
                    processed
                ),
                "total_tokens": total_tokens,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "average_total_tokens_per_processed_record": self._safe_divide(
                    total_tokens,
                    processed,
                    digits=3
                )
            }

        return summary

    def _build_attempt_status_summary(
        self
    ):
        attempts = self._read_array_file(
            self.report_root / "attempts.json"
        )
        by_status = {}
        by_error_type = {}

        for item in attempts:
            status = str(
                item.get("status") or "unknown"
            )
            by_status[status] = by_status.get(
                status,
                0
            ) + 1

            error = item.get("error") or {}
            error_type = error.get("error_type")

            if error_type:
                by_error_type[error_type] = by_error_type.get(
                    error_type,
                    0
                ) + 1

        return {
            "total_attempt_rows": len(attempts),
            "by_status": dict(sorted(by_status.items())),
            "by_error_type": dict(sorted(by_error_type.items()))
        }

    def _build_failure_reason_summary(
        self
    ):
        by_status = {}
        by_error_type = {}

        if not self.response_chunk_root.exists():
            return {
                "by_status": {},
                "by_error_type": {}
            }

        for subject_dir in sorted(
            path for path in self.response_chunk_root.iterdir()
            if path.is_dir()
        ):
            subject = self.normalize_subject(
                subject_dir.name
            )
            payload = self._subject_report_payload(
                subject
            )

            for group_name in ["failures", "invalid_json", "skipped"]:
                for item in payload[group_name]:
                    status = str(
                        item.get("status") or group_name
                    )
                    by_status[status] = by_status.get(
                        status,
                        0
                    ) + 1

                    error = item.get("error") or {}
                    error_type = error.get("error_type")

                    if error_type:
                        by_error_type[error_type] = by_error_type.get(
                            error_type,
                            0
                        ) + 1

        return {
            "by_status": dict(sorted(by_status.items())),
            "by_error_type": dict(sorted(by_error_type.items()))
        }

    def _build_model_summary(
        self
    ):
        by_model = {}

        if not self.response_chunk_root.exists():
            return by_model

        for subject_dir in sorted(
            path for path in self.response_chunk_root.iterdir()
            if path.is_dir()
        ):
            subject = self.normalize_subject(
                subject_dir.name
            )
            payload = self._subject_report_payload(
                subject
            )

            for item in payload["records"]:
                model_name = str(
                    item.get("model_name") or "UNKNOWN"
                )
                usage = item.get("usage") or {}

                if model_name not in by_model:
                    by_model[model_name] = {
                        "records": 0,
                        "estimated_prompt_tokens": 0,
                        "prompt_tokens": 0,
                        "thinking_tokens": 0,
                        "cached_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0
                    }

                by_model[model_name]["records"] += 1
                by_model[model_name]["estimated_prompt_tokens"] += int(
                    usage.get("estimated_prompt_tokens") or 0
                )
                by_model[model_name]["prompt_tokens"] += int(
                    usage.get("prompt_token_count") or 0
                )
                by_model[model_name]["thinking_tokens"] += int(
                    usage.get("thoughts_token_count") or 0
                )
                by_model[model_name]["cached_tokens"] += int(
                    usage.get("cached_content_token_count") or 0
                )
                by_model[model_name]["output_tokens"] += int(
                    usage.get("candidates_token_count") or 0
                )
                by_model[model_name]["total_tokens"] += int(
                    usage.get("total_token_count") or 0
                )

        for model_name, item in by_model.items():
            item["average_total_tokens_per_record"] = self._safe_divide(
                item["total_tokens"],
                item["records"],
                digits=3
            )

        return dict(sorted(by_model.items()))

    def build_final_execution_report(
        self,
        summary
    ):
        metrics = summary.get("metrics", {})

        return {
            "run": {
                "run_id": summary.get("run_id"),
                "run_name": summary.get("run_name"),
                "started_at": summary.get("started_at"),
                "ended_at": summary.get("ended_at"),
                "duration_seconds": metrics.get("duration_seconds")
            },
            "overview": {
                "total_selected": summary.get("total_selected"),
                "processed": summary.get("processed"),
                "success": summary.get("success"),
                "failed": summary.get("failed"),
                "invalid_json": summary.get("invalid_json"),
                "skipped": summary.get("skipped"),
                "success_rate": metrics.get("success_rate"),
                "failure_rate": metrics.get("failure_rate")
            },
            "tokens": {
                "estimated_prompt_tokens": summary.get("estimated_prompt_tokens"),
                "actual_prompt_tokens": summary.get("actual_prompt_tokens"),
                "output_tokens": summary.get("output_tokens"),
                "thinking_tokens": summary.get("thinking_tokens"),
                "cached_tokens": summary.get("cached_tokens"),
                "total_tokens": summary.get("total_tokens"),
                "average_total_tokens_per_processed_record": metrics.get(
                    "average_total_tokens_per_processed_record"
                ),
                "average_prompt_tokens_per_success": metrics.get(
                    "average_prompt_tokens_per_success"
                ),
                "average_output_tokens_per_success": metrics.get(
                    "average_output_tokens_per_success"
                )
            },
            "api_execution": {
                "total_attempts": summary.get("total_attempts"),
                "model_switches": summary.get("model_switches"),
                "attempt_statuses": self._build_attempt_status_summary(),
                "failure_patterns": self._build_failure_reason_summary()
            },
            "content_mix": {
                "text_only": summary.get("text_only"),
                "image_only": summary.get("image_only"),
                "text_plus_image": summary.get("text_plus_image"),
                "no_content": summary.get("no_content")
            },
            "by_subject": self._build_subject_execution_summary(),
            "by_model": self._build_model_summary(),
            "report_index": summary.get("report_index", {})
        }

    def build_final_execution_report_text(
        self,
        report
    ):
        lines = [
            "FINAL GEMINI EXECUTION REPORT",
            "=" * 40,
            f"Run ID            : {report['run'].get('run_id')}",
            f"Run Name          : {report['run'].get('run_name')}",
            f"Started At        : {report['run'].get('started_at')}",
            f"Ended At          : {report['run'].get('ended_at')}",
            f"Duration Seconds  : {report['run'].get('duration_seconds')}",
            "",
            "Overview",
            f"Total Selected    : {report['overview'].get('total_selected')}",
            f"Processed         : {report['overview'].get('processed')}",
            f"Success           : {report['overview'].get('success')}",
            f"Failed            : {report['overview'].get('failed')}",
            f"Invalid JSON      : {report['overview'].get('invalid_json')}",
            f"Skipped           : {report['overview'].get('skipped')}",
            f"Success Rate      : {report['overview'].get('success_rate')}",
            f"Failure Rate      : {report['overview'].get('failure_rate')}",
            "",
            "Token Usage",
            f"Estimated Prompt  : {report['tokens'].get('estimated_prompt_tokens')}",
            f"Actual Prompt     : {report['tokens'].get('actual_prompt_tokens')}",
            f"Output Tokens     : {report['tokens'].get('output_tokens')}",
            f"Thinking Tokens   : {report['tokens'].get('thinking_tokens')}",
            f"Cached Tokens     : {report['tokens'].get('cached_tokens')}",
            f"Total Tokens      : {report['tokens'].get('total_tokens')}",
            f"Avg Total/Record  : {report['tokens'].get('average_total_tokens_per_processed_record')}",
            "",
            "API Execution",
            f"Total Attempts    : {report['api_execution'].get('total_attempts')}",
            f"Model Switches    : {report['api_execution'].get('model_switches')}",
            f"Attempt Statuses  : {report['api_execution']['attempt_statuses'].get('by_status')}",
            f"Failure Statuses  : {report['api_execution']['failure_patterns'].get('by_status')}",
            f"Failure Errors    : {report['api_execution']['failure_patterns'].get('by_error_type')}",
            "",
            "By Subject"
        ]

        for subject, item in report.get("by_subject", {}).items():
            lines.append(
                f"{subject}: processed={item.get('processed')} success={item.get('success')} "
                f"failed={item.get('failures')} invalid_json={item.get('invalid_json')} "
                f"skipped={item.get('skipped')} total_tokens={item.get('total_tokens')}"
            )

        lines.append("")
        lines.append("By Model")

        for model_name, item in report.get("by_model", {}).items():
            lines.append(
                f"{model_name}: records={item.get('records')} prompt_tokens={item.get('prompt_tokens')} "
                f"output_tokens={item.get('output_tokens')} total_tokens={item.get('total_tokens')}"
            )

        return "\n".join(lines) + "\n"

    def save_summary(
        self
    ):
        with self.lock:
            self.summary["ended_at"] = datetime.now().isoformat()

            self.summary["metrics"] = self.build_summary_metrics()

            self.summary["report_index"] = self.build_report_index()

            self.summary["response_storage"] = {
                "mode": "subject_wise_json",
                "chunk_size": self.chunk_size,
                "chunk_root": str(self.response_chunk_root),
                "prompt_storage": "disabled",
                "structure": {
                    "example": "responses_by_subject/MATH/success/MATH_chunk_000001.json",
                    "description": (
                        "Each subject has success/ and failed/ folders. "
                        "All files are normal JSON arrays, not JSONL."
                    )
                }
            }

            self.summary["subject_chunk_state"] = self.make_json_safe(
                self.subject_chunk_state
            )

            preflight_token_usage_summary = (
                self.build_preflight_token_usage_summary()
            )

            self.summary["preflight_token_usage_summary"] = (
                preflight_token_usage_summary
            )

            self.write_json(
                self.report_root / "run_summary.json",
                self.summary
            )

            self.write_json(
                self.report_root / "preflight_token_usage_summary.json",
                preflight_token_usage_summary
            )

            final_execution_report = self.build_final_execution_report(
                self.summary
            )

            self.write_json(
                self.report_root / "final_execution_report.json",
                final_execution_report
            )

            with open(
                self.report_root / "final_execution_report.txt",
                "w",
                encoding="utf-8"
            ) as f:
                f.write(
                    self.build_final_execution_report_text(
                        final_execution_report
                    )
                )

            self.append_json_array(
                self.global_usage_file,
                {
                    "timestamp": datetime.now().isoformat(),
                    "run_id": self.run_id,
                    "status": "run_summary",
                    "summary": self.summary
                }
            )

            return self.summary
