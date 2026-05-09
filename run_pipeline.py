# run_pipeline.py

import argparse
import datetime
import logging
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Current-case pointer (used when no CLI argument is provided)
DEFAULT_CLIENT = "client_name_001"


def run_step(label, cmd):
    logging.info("Running: %s", label)
    process = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert process.stdout is not None
    for line in process.stdout:
        logging.info("[%s] %s", label, line.rstrip())

    return process.wait()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the forensic revenue pipeline for a client folder."
    )
    parser.add_argument(
        "client",
        nargs="?",
        default=DEFAULT_CLIENT,
        help="Client folder name under 'clients/' (default: current-case pointer).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    client_name = args.client

    client_dir = BASE_DIR / "clients" / client_name
    client_config_path = client_dir / "client_config.py"
    if not client_config_path.exists():
        raise FileNotFoundError(
            f"Client config not found: {client_config_path}. "
            f"Expected structure: clients/{client_name}/client_config.py"
        )

    log_dir = client_dir / "output"
    log_dir.mkdir(exist_ok=True)
    log_filename = log_dir / f"forensic_audit_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filename, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    steps = [
        (
            "Cleanup",
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util; "
                    "from cleanup_engine import run_cleanup; "
                    f"cfg=r'{client_config_path}'; "
                    "spec=importlib.util.spec_from_file_location('client_config', cfg); "
                    "mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
                    "run_cleanup(mod.config)"
                ),
            ],
        ),
        (
            "Loss Projection",
            [
                sys.executable,
                str(BASE_DIR / "templates" / "loss_projection_engine.py"),
                "--config",
                str(client_config_path),
            ],
        ),
    ]

    logging.info("Client selected: %s", client_name)
    for label, cmd in steps:
        return_code = run_step(label, cmd)
        if return_code != 0:
            logging.error("%s failed with exit code %s. Halting.", label, return_code)
            break
    else:
        logging.info("Pipeline complete.")
        logging.info("Log written to: %s", log_filename)


if __name__ == "__main__":
    main()
