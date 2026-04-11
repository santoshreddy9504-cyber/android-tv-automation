#!/usr/bin/env python3
"""
Android TV Automated QA Test Runner
====================================
Runs the full automated test suite against the configured app.

Configure your app by setting CLIENT_CONFIG in .env (see .env.example).

Usage:
    python run_auto_test.py
    python run_auto_test.py --ip 192.168.1.100 --debug
    python run_auto_test.py --client clients/myapp.json
"""

import argparse
import os
import sys

from utils.logger import setup_logging
from utils.helpers import ensure_output_dirs, print_banner
from config import config


def parse_args():
    p = argparse.ArgumentParser(description="Android TV Automated QA Test Runner")
    p.add_argument("--ip",       default=None,  help="Device IP address")
    p.add_argument("--port",     type=int, default=None, help="ADB port (default 5555)")
    p.add_argument("--client",   default=None,  help="Path to client JSON config (overrides CLIENT_CONFIG in .env)")
    p.add_argument("--package",  default=None,  help="App package name (overrides client config)")
    p.add_argument("--email",    default=None,  help="Login email")
    p.add_argument("--password", default=None,  help="Login password")
    p.add_argument("--debug",    action="store_true", help="Enable debug logging")
    return p.parse_args()


def main():
    args = parse_args()

    # If --client is passed, reload client config before anything else reads it
    if args.client:
        os.environ["CLIENT_CONFIG"] = args.client
        from config import _load_client_config
        new_client = _load_client_config()
        config.client          = new_client
        config.app.app_name    = new_client.app_name
        config.app.package_name    = new_client.package_name
        config.app.launch_activity = new_client.launch_activity

    if args.ip:       config.device.device_ip  = args.ip
    if args.port:     config.device.adb_port   = args.port
    if args.package:  config.app.package_name  = args.package
    if args.email:    config.login.email        = args.email
    if args.password: config.login.password     = args.password

    setup_logging("DEBUG" if args.debug else "INFO")
    ensure_output_dirs()
    print_banner()

    from automation.test_runner import AutomatedTestRunner
    runner = AutomatedTestRunner()
    runner.run()


if __name__ == "__main__":
    main()
