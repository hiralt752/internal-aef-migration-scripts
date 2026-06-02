import random


def get_backoff_delay(
    attempt
):
    """
    Exponential backoff + jitter.

    Example:

    attempt=0 -> 1.4s
    attempt=1 -> 2.8s
    attempt=2 -> 4.5s
    """

    return (
        (2 ** attempt)
        + random.uniform(
            0.5,
            2
        )
    )