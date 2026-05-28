from __future__ import annotations

import hashlib
import platform
import shutil
import sys
import uuid
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Dict, Optional

import yaml

from qoala_bench.config import RootConfig, inject_run_metadata


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def snapshot_environment(packages: Optional[list[str]] = None) -> Dict[str, object]:
    packages = packages or ["netsquid", "qoala", "numpy", "pydantic", "pyyaml"]
    pkgs = {}
    for name in packages:
        try:
            pkgs[name] = pkg_version(name)
        except PackageNotFoundError:
            pkgs[name] = None

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": pkgs,
    }


@dataclass(frozen=True)
class DatasetPaths:
    root: Path
    dataset_yaml: Path
    meta_yaml: Path
    env_yaml: Path
    artifacts_config: Path
    artifacts_programs: Path
    artifacts_compilator: Path
    raw: Path
    analysis: Path


def create_dataset_dir(
    base_dir: str = "results", name: Optional[str] = None
) -> DatasetPaths:
    uid = uuid.uuid4().hex
    folder_name = name if name else f"dataset-{uid}"
    root = Path(base_dir) / folder_name

    # When an explicit name is given, refuse to reuse an existing directory.
    # Silently appending to existing raw/*.pkl.gz files would corrupt results.
    if name is not None and root.exists():
        raise FileExistsError(
            f"Dataset '{root}' already exists. Delete it first or choose a different name."
        )
    dataset_yaml = root / "dataset.yaml"
    meta_yaml = root / "meta.yaml"
    env_yaml = root / "environment.yaml"

    artifacts_config = root / "artifacts" / "config"
    artifacts_programs = root / "artifacts" / "programs"
    artifacts_compilator = root / "artifacts" / "compilator"
    raw = root / "raw"
    analysis = root / "analysis"

    for p in [
        root,
        artifacts_config,
        artifacts_programs,
        artifacts_compilator,
        raw,
        analysis,
    ]:
        safe_mkdir(p)

    return DatasetPaths(
        root=root,
        dataset_yaml=dataset_yaml,
        meta_yaml=meta_yaml,
        env_yaml=env_yaml,
        artifacts_config=artifacts_config,
        artifacts_programs=artifacts_programs,
        artifacts_compilator=artifacts_compilator,
        raw=raw,
        analysis=analysis,
    )


def copy_config_into_dataset(src_config_path: str, dst_dir: Path) -> Path:
    dst_path = dst_dir / "params.json"
    safe_mkdir(dst_dir)
    shutil.copy(src_config_path, dst_path)
    return dst_path


def copy_program_iqoala(program_dir: str, dst_dir: Path) -> Dict[str, Path]:
    """Copy alice.iqoala and bob.iqoala into dst_dir."""
    src = Path(program_dir)
    alice_src = src / "alice.iqoala"
    bob_src = src / "bob.iqoala"
    if not alice_src.exists() or not bob_src.exists():
        raise FileNotFoundError(f"Missing alice.iqoala or bob.iqoala in {program_dir}")

    safe_mkdir(dst_dir)
    alice_dst = dst_dir / "alice.iqoala"
    bob_dst = dst_dir / "bob.iqoala"
    shutil.copy(alice_src, alice_dst)
    shutil.copy(bob_src, bob_dst)
    return {"alice": alice_dst, "bob": bob_dst}


def write_yaml(path: Path, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def freeze_config_to_dataset_yaml(
    cfg: RootConfig, dataset_paths: DatasetPaths, uuid_str: str, copied_config_rel: str
) -> None:
    """
    Write resolved dataset.yaml with injected uuid/ran/dataset_version and with config_path rewritten
    to point inside the dataset.
    """
    cfg = inject_run_metadata(cfg, uuid_str)
    cfg.params.config_path = copied_config_rel
    write_yaml(dataset_paths.dataset_yaml, cfg.model_dump(mode="python"))


def write_meta(dataset_paths: DatasetPaths, hashes: Dict[str, str]) -> None:
    write_yaml(dataset_paths.meta_yaml, {"hashes": hashes})


def write_environment(dataset_paths: DatasetPaths) -> None:
    env = snapshot_environment()
    write_yaml(dataset_paths.env_yaml, env)
