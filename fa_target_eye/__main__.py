"""
Main module for fa_prom_target_eye, a dynamic target discovery service for
Prometheus.

It provides a REST API for registering targets and persists this data to disk
in files containing JSON that Prometheus can understand.

This service is meant to run on the same machine as the Prometheus server it is
registering targets for, or, at least, sharing access to the Prometheus
server's directory for file-based service discovery.
"""
import argparse as ap
import os

from .rest_api import run_rest_api


def parse_args() -> ap.Namespace:
    """"Parses the command-line arguments

    Only optional argument is an INI-style Python config file

    It is intended for development purposes.

    Normally no command-line arguments are passed in and Target-eye is started
    by simply running

      python -m fa_target_eye

    All configuration in that case is done through environment variables.
    """
    parser = ap.ArgumentParser(formatter_class=ap.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        "config_file",
        help="Path to TOML config file for running REST API with hypercorn",
        nargs="?",
        default=os.getenv("CONFIG_FILE", "CONFIG_FILE env variable"),
    )

    return parser.parse_args()


if __name__ == "__main__":
    ARGS = parse_args()
    run_rest_api(ARGS.config_file)
