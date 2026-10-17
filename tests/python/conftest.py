"""Seal keys for test projects stay out of the operator key store."""
import os
import tempfile

os.environ.setdefault("MATLAB_HARNESS_KEY_DIR", tempfile.mkdtemp(prefix="matlab-harness-test-keys-"))
