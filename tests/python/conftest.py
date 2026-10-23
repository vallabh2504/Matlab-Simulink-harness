"""Seal keys for test projects stay out of the operator key store."""
import atexit
import os
import shutil
import tempfile

if "MATLAB_HARNESS_KEY_DIR" not in os.environ:
    os.environ["MATLAB_HARNESS_KEY_DIR"] = tempfile.mkdtemp(prefix="matlab-harness-test-keys-")
    atexit.register(shutil.rmtree, os.environ["MATLAB_HARNESS_KEY_DIR"], True)
