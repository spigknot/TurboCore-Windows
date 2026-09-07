"""Sonda read-only do bucket R2 (lista prefixos top-level)."""
import json
import pathlib
import sys

sys.path.insert(0, "D:/Projetos/TurboCore/scripts")

ROOT = pathlib.Path("D:/Projetos/TurboCore")
cfg = json.loads((ROOT / "release" / "r2_config.json").read_text(encoding="utf-8"))

import boto3  # noqa: E402

s3 = boto3.client(
    "s3",
    endpoint_url=cfg["endpoint"],
    aws_access_key_id=cfg["access_key_id"],
    aws_secret_access_key=cfg["secret_access_key"],
    region_name="auto",
)
seen = set()
count = 0
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=cfg["bucket"]):
    for obj in page.get("Contents", []):
        count += 1
        seen.add(obj["Key"].split("/", 1)[0])
print("bucket:", cfg["bucket"], "| objetos:", count)
print("top-level:", sorted(seen))
