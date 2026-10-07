"""CPU evaluation subprocess entry point with fixed, non-sensitive diagnostics."""

import argparse
from pathlib import Path
import sys

from .audio import validate_input_audio
from .inference import run_prediction
from .output import OutputValidationError, write_outputs
from .provenance import safe_path, validate_checkpoint


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid worker arguments")


def main(argv=None) -> int:
    parser = Parser(description="Pinned CPU piano AMT evaluation worker")
    parser.add_argument("--input-audio", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--device", required=True, choices=["cpu"])
    try:
        args = parser.parse_args(argv)
        audio = validate_input_audio(args.input_audio)
        digest = validate_checkpoint(args.checkpoint, expected_sha256=args.checkpoint_sha256)
        safe_path(args.output_dir)
    except SystemExit as error:
        return int(error.code)
    except (ValueError, OSError):
        print("worker setup failed", file=sys.stderr)
        return 2
    if args.output_dir.exists():
        print("worker output failed", file=sys.stderr)
        return 4
    try:
        prediction = run_prediction(args.input_audio, checkpoint=args.checkpoint, device=args.device)
    except OutputValidationError:
        print("worker output failed", file=sys.stderr)
        return 4
    except Exception:
        print("worker inference failed", file=sys.stderr)
        return 3
    try:
        write_outputs(args.output_dir, prediction, input_sha256=audio.sha256, checkpoint_sha256=digest, device=args.device)
    except (ValueError, OSError):
        print("worker output failed", file=sys.stderr)
        return 4
    print("worker output ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
