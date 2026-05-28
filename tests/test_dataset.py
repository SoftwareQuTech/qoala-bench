"""Tests for :mod:`qoala_bench.dataset`.

Covers the file-system helpers: hashing, environment snapshots,
dataset-folder creation, and the YAML/metadata writers. Every test
operates inside ``tmp_path`` so the real ``results/`` folder is never
touched.
"""

from __future__ import annotations

import json

import pytest
import yaml

from qoala_bench.dataset import (
    DatasetPaths,
    copy_config_into_dataset,
    create_dataset_dir,
    safe_mkdir,
    sha256_file,
    snapshot_environment,
    write_environment,
    write_meta,
    write_yaml,
)


def test_sha256_file_is_deterministic_and_well_formed(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"hello qoala")

    h1 = sha256_file(f)
    h2 = sha256_file(f)

    assert h1 == h2
    assert h1.startswith("sha256:")
    # 64 hex chars after the prefix
    assert len(h1) == len("sha256:") + 64
    int(h1.removeprefix("sha256:"), 16)  # raises on malformed hex


def test_sha256_file_distinguishes_different_contents(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"alpha")
    b.write_bytes(b"beta")
    assert sha256_file(a) != sha256_file(b)


def test_sha256_file_streams_larger_than_chunk_size(tmp_path):
    # The implementation reads in 1 MiB chunks; verify it still works on a
    # file slightly larger than one chunk.
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * (1024 * 1024 + 128))
    h = sha256_file(path)
    assert h.startswith("sha256:")


def test_safe_mkdir_creates_parents(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    safe_mkdir(target)
    assert target.is_dir()


def test_safe_mkdir_is_idempotent(tmp_path):
    target = tmp_path / "exists"
    safe_mkdir(target)
    safe_mkdir(target)  # second call must not raise
    assert target.is_dir()


def test_snapshot_environment_shape():
    env = snapshot_environment()
    assert "python" in env
    assert "platform" in env
    assert "packages" in env
    assert isinstance(env["packages"], dict)


def test_snapshot_environment_with_known_missing_package():
    env = snapshot_environment(packages=["this-package-definitely-does-not-exist"])
    assert env["packages"]["this-package-definitely-does-not-exist"] is None


def test_create_dataset_dir_with_explicit_name(tmp_path):
    paths = create_dataset_dir(base_dir=str(tmp_path), name="my-bench")

    assert isinstance(paths, DatasetPaths)
    assert paths.root == tmp_path / "my-bench"
    assert paths.root.is_dir()
    assert paths.artifacts_config.is_dir()
    assert paths.artifacts_programs.is_dir()
    assert paths.artifacts_compilator.is_dir()
    assert paths.raw.is_dir()
    assert paths.analysis.is_dir()


def test_create_dataset_dir_with_uuid_name_when_unspecified(tmp_path):
    paths = create_dataset_dir(base_dir=str(tmp_path))
    assert paths.root.name.startswith("dataset-")
    # 32 hex chars for the uuid4 .hex
    assert len(paths.root.name) == len("dataset-") + 32


def test_create_dataset_dir_named_collision_raises(tmp_path):
    create_dataset_dir(base_dir=str(tmp_path), name="taken")
    with pytest.raises(FileExistsError, match="already exists"):
        create_dataset_dir(base_dir=str(tmp_path), name="taken")


def test_copy_config_into_dataset_writes_params_json(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(json.dumps({"hello": "world"}))

    dst_dir = tmp_path / "dataset" / "artifacts" / "config"
    out = copy_config_into_dataset(str(src), dst_dir)

    assert out == dst_dir / "params.json"
    assert out.is_file()
    assert json.loads(out.read_text()) == {"hello": "world"}


def test_write_yaml_round_trips(tmp_path):
    path = tmp_path / "doc.yaml"
    payload = {"alpha": [1, 2], "beta": {"x": 1}}
    write_yaml(path, payload)

    loaded = yaml.safe_load(path.read_text())
    assert loaded == payload


def test_write_meta_writes_hashes_under_top_level_key(tmp_path):
    paths = create_dataset_dir(base_dir=str(tmp_path), name="meta-test")
    write_meta(paths, {"artifacts/config/params.json": "sha256:abc"})

    loaded = yaml.safe_load(paths.meta_yaml.read_text())
    assert loaded == {"hashes": {"artifacts/config/params.json": "sha256:abc"}}


def test_write_environment_emits_python_and_packages(tmp_path):
    paths = create_dataset_dir(base_dir=str(tmp_path), name="env-test")
    write_environment(paths)

    loaded = yaml.safe_load(paths.env_yaml.read_text())
    assert "python" in loaded
    assert "platform" in loaded
    assert "packages" in loaded
    assert isinstance(loaded["packages"], dict)
