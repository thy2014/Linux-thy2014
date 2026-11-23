#!/usr/bin/env python3
"""启动老师端：python run_teacher.py [--room 六年级一班]"""
import sys

from thyclass.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["teacher", *sys.argv[1:]]))
