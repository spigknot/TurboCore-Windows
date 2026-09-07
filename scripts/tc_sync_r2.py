#!/usr/bin/env python3
"""Publica a pasta sync no Cloudflare R2 (S3) e gera o sync_manifest.json (schema 2).

Uso:
    python scripts/tc_sync_r2.py --package release/generated/<VERSAO>/package --version <VERSAO>

Credenciais em release/r2_config.json (NUNCA commitar). Bucket turbocore-windows.
"""
import argparse
import base64
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

import boto3  # noqa: E402


KEY_PATH = ROOT / "release" / "update_private_key.pem"

# Top-levels que NÃO entram no manifesto sync (vão só no full/instalador).
SYNC_EXCLUDED_TOP_LEVEL: set[str] = set()


def snapshot(package: pathlib.Path) -> dict[str, dict]:
    files: dict[str, dict] = {}
    for path in sorted(package.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        relative = path.relative_to(package).as_posix()
        if relative.split("/", 1)[0] in SYNC_EXCLUDED_TOP_LEVEL:
            continue
        if "__pycache__" in relative.split("/") or relative.endswith(".pyc"):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files[relative] = {"sha256": digest.hexdigest(), "size": path.stat().st_size}
    return files


def canonical_manifest(manifest: dict) -> bytes:
    files = sorted(
        (
            {
                "path": str(entry["path"]),
                "sha256": str(entry["sha256"]).lower(),
                "size": int(entry["size"]),
                "drive_id": str(entry.get("drive_id") or ""),
                "github_url": str(entry.get("github_url") or ""),
            }
            for entry in manifest.get("files", [])
        ),
        key=lambda item: item["path"],
    )
    payload = {
        "schema": int(manifest.get("schema") or 0),
        "version": str(manifest.get("version") or ""),
        "created_at": str(manifest.get("created_at") or ""),
        "files": files,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict, key_path: pathlib.Path = KEY_PATH) -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not key_path.is_file():
        raise SystemExit("chave privada de atualização não encontrada")
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    signature = private_key.sign(canonical_manifest(manifest), padding.PKCS1v15(), hashes.SHA256())
    manifest["signature"] = base64.b64encode(signature).decode("ascii")


def build_manifest(files: dict[str, dict], version: str, public_base: str) -> dict:
    return {
        "schema": 2,
        "version": version,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": [
            {
                "path": path,
                "sha256": entry["sha256"],
                "size": entry["size"],
                "drive_id": "",
                "github_url": f"{public_base}/{path}",
            }
            for path, entry in files.items()
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, help="pasta onedir full (ex.: .../package)")
    ap.add_argument("--version", required=True, help="versão do manifesto (ex.: 20260907_001)")
    ap.add_argument("--quiet", action="store_true", help="mostrar somente o resumo do sync")
    args = ap.parse_args()

    cfg_path = ROOT / "release" / "r2_config.json"
    if not cfg_path.is_file():
        raise SystemExit("release/r2_config.json não encontrado (credenciais do R2)")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    package = pathlib.Path(args.package)
    if not package.is_dir():
        raise SystemExit(f"pasta do pacote não encontrada: {package}")

    files = snapshot(package)
    if not args.quiet:
        print(f"pacote: {len(files)} arquivos")

    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        region_name="auto",
    )
    bucket = cfg["bucket"]
    public_base = cfg["public_base"].rstrip("/")

    def _md5(path: pathlib.Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # Diff por hash: uma única listagem (ETags) vs o MD5 local — sobe só o que mudou
    remote_etags: dict[str, str] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            remote_etags[str(obj["Key"])] = str(obj.get("ETag") or "").strip('"')
    to_upload = {}
    for path, entry in files.items():
        if remote_etags.get(path) != _md5(package / path):
            to_upload[path] = entry

    upload_count = len(to_upload)
    if not args.quiet:
        print(f"subir: {upload_count}")
    for index, (path, entry) in enumerate(to_upload.items(), 1):
        with (package / path).open("rb") as handle:
            s3.put_object(Bucket=bucket, Key=path, Body=handle)
        if not args.quiet and (index % 25 == 0 or index == len(to_upload)):
            print(f"  upload {index}/{len(to_upload)}")
    if not args.quiet:
        print("upload concluído")

    manifest = build_manifest(files, args.version, public_base)
    sign_manifest(manifest)
    body = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    s3.put_object(Bucket=bucket, Key="sync_manifest.json", Body=body, ContentType="application/json")
    if args.quiet:
        print(
            f"PASS: sync-r2 version={args.version} uploaded={upload_count} "
            f"unchanged={len(files) - upload_count} manifest=sync_manifest.json"
        )
    else:
        print("sync_manifest.json publicado no R2")


if __name__ == "__main__":
    main()
