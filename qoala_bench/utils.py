import gzip
import json
import os
import pickle
from dataclasses import dataclass
from typing import Any, Dict

import yaml


def load_config(config_path: str) -> Dict[str, Any]:
    """Loads the configuration from a JSON file."""
    with open(config_path, "r") as file:
        data: Dict[str, Any] = json.load(file)
    return data


@dataclass(frozen=True)
class SimulationResult:
    """Stores the outcome and duration of a experiment."""

    success: bool
    duration: int


def load_all_results_from_directory(directory: str):
    """
    Loads all gzip-compressed pickle (.pkl.gz) files from the given directory.

    Args:
        directory (str): Path to the directory containing result files.

    Returns:
        List[Any]: A list of all loaded results.
    """
    all_results = []

    # Get a sorted list of all .pkl.gz files in the directory
    pickle_files = sorted(
        [
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.endswith(".pkl.gz")  # Now correctly loading compressed files
        ]
    )

    # print(f"📂 Found {len(pickle_files)} result files in {directory}")

    for file in pickle_files:
        try:
            with gzip.open(file, "rb") as f:  # Open with gzip
                while True:
                    try:
                        result = pickle.load(f)  # Load each object from the file
                        all_results.append(result)
                    except EOFError:
                        break  # Stop when the file ends
        except Exception as e:
            print(f"⚠️ Error loading {file}: {e}")

    return all_results


def load_yaml(yaml_path: str) -> Dict[str, Any]:
    with open(yaml_path, "r") as f:
        data: Dict[str, Any] = yaml.safe_load(f)
    return data
