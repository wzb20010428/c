#!/usr/bin/env python3

import os
import sys

# load pre-defined QA model
sys.path.append(os.environ["TRITON_QA_PYTHON_MODEL_DIR"])
from python_subadd import *
