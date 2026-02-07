#!/usr/bin/env python3
"""Launcher script - run from a data folder to start the GUI with that folder's data."""
import os
import sys

# Add parent directories to path so we can import the main modules
data_dir = os.path.dirname(os.path.abspath(__file__))
code_dir = os.path.dirname(os.path.dirname(data_dir))
sys.path.insert(0, code_dir)

from reconciliation_gui import main
main(data_dir=data_dir)
