import time


class ProgressLogger:
    def __init__(
        self,
        total=None,
        log_every=100,
        log_seconds=30
    ):
        self.total = total
        self.log_every = log_every
        self.log_seconds = log_seconds
        self.start_time = time.time()
        self.last_log_time = self.start_time

    def log(
        self,
        processed,
        success,
        failed,
        image_questions=0,
        total_images=0,
        current_file=None,
        force=False
    ):
        now = time.time()

        should_log = (
            force
            or processed == 1
            or processed % self.log_every == 0
            or now - self.last_log_time >= self.log_seconds
        )

        if not should_log:
            return

        elapsed = now - self.start_time
        rate = processed / elapsed if elapsed else 0

        if self.total:
            remaining = max(
                self.total - processed,
                0
            )

            eta_seconds = (
                remaining / rate
                if rate
                else 0
            )

            eta_text = f"{eta_seconds / 60:.1f} min"
            total_text = f"/{self.total:,}"

        else:
            eta_text = "unknown"
            total_text = ""

        print(
            f"[PROGRESS] "
            f"Processed={processed:,}{total_text} | "
            f"Success={success:,} | "
            f"Failed={failed:,} | "
            f"Image Questions={image_questions:,} | "
            f"Images={total_images:,} | "
            f"Rate={rate:.2f}/sec | "
            f"ETA={eta_text}",
            flush=True
        )

        if current_file:
            print(
                f"[CURRENT FILE] {current_file}",
                flush=True
            )

        self.last_log_time = now