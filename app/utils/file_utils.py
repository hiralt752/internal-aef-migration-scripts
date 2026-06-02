import json
import os

import aiofiles
import pandas as pd


def create_directory(
    path
):
    os.makedirs(
        path,
        exist_ok=True
    )


async def save_json(
    filepath,
    data
):

    async with aiofiles.open(
        filepath,
        "w",
        encoding="utf-8"
    ) as f:

        await f.write(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )
        )


def save_csv(
    filepath,
    records
):

    df = pd.DataFrame(records)

    df.to_csv(
        filepath,
        index=False,
        encoding="utf-8"
    )