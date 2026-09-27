"""Command line entry point for the isolated Basic Pitch worker."""

import argparse
import importlib.metadata
from pathlib import Path
import sys
from collections.abc import Sequence

from musicsheet_basic_pitch_worker.audio import InvalidAudioError, validate_input_audio
from musicsheet_basic_pitch_worker.inference import InferenceError, run_prediction
from musicsheet_basic_pitch_worker.output import (
    OutputError,
    ResultValidationError,
    build_result,
    write_outputs,
)
from musicsheet_basic_pitch_worker.provenance import BASIC_PITCH_SOURCE_COMMIT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="basic-pitch-worker")
    parser.add_argument("--input-audio", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    try:
        validate_input_audio(arguments.input_audio)
    except InvalidAudioError as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2

    if arguments.output_dir.exists() or arguments.output_dir.is_symlink():
        print(f"output error: output path already exists: {arguments.output_dir}", file=sys.stderr)
        return 4

    try:
        prediction = run_prediction(arguments.input_audio)
    except InferenceError as error:
        print(f"inference error: {error}", file=sys.stderr)
        return 3

    try:
        package_version = importlib.metadata.version("basic-pitch")
    except importlib.metadata.PackageNotFoundError as error:
        print(f"inference error: Basic Pitch package metadata is unavailable: {error}", file=sys.stderr)
        return 3

    try:
        result = build_result(
            prediction,
            package_version=package_version,
            source_commit=BASIC_PITCH_SOURCE_COMMIT,
        )
        write_outputs(arguments.output_dir, result, prediction.midi_data)
    except (OutputError, ResultValidationError) as error:
        print(f"output error: {error}", file=sys.stderr)
        return 4

    return 0
