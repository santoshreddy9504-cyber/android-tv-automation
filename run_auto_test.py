#!/usr/bin/env python3
"""
Fully Automated QA Test Runner for ROD TV
==========================================
Run this script — it will do everything automatically:
  1. Connect to Android TV via ADB
  2. Launch ROD TV app
  3. Navigate every section using simulated remote
  4. Play videos and measure start time
  5. Test playback controls (pause/resume/seek)
  6. Run stability stress test
  7. Generate detailed HTML + JSON QA report

Usage:
    python run_auto_test.py
    python run_auto_test.py --ip 192.168.2.29 --debug
"""

import argparse
import sys

from utils.logger import setup_logging
from utils.helpers import ensure_output_dirs, print_banner
from config import config


def parse_args():
    p = argparse.ArgumentParser(description="ROD TV Automated QA Test Runner")
    p.add_argument("--ip",       default=None, help="Device IP (default: 192.168.2.29)")
    p.add_argument("--port",     type=int, default=None)
    p.add_argument("--package",  default=None)
    p.add_argument("--email",    default=None, help="Login email for ROD TV")
    p.add_argument("--password", default=None, help="Login password for ROD TV")
    p.add_argument("--debug",    action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.ip:       config.device.device_ip    = args.ip
    if args.port:     config.device.adb_port      = args.port
    if args.package:  config.app.package_name     = args.package
    if args.email:    config.login.email          = args.email
    if args.password: config.login.password       = args.password

    setup_logging("DEBUG" if args.debug else "INFO")
    ensure_output_dirs()
    print_banner()

    from automation.test_runner import AutomatedTestRunner
    runner = AutomatedTestRunner()
    runner.run()


if __name__ == "__main__":
    main()
