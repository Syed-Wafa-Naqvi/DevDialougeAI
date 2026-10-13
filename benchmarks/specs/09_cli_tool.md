# Spec 09: CLI File Organizer Utility

## Overview
Build a command-line file organizing utility in pure Python.

## Requirements
- CLI flags `--target-dir`, `--organize-by-ext`, `--delete-empty`.
- Sorts files into subdirectories named after file extensions (e.g. `.pdf` -> `PDFs/`).
- Safely handles filename collisions by appending numeric suffixes.
- Prints a console summary table of moved files and freed directory space.
