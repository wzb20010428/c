#!/usr/bin/python

# Copyright 2022-2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of NVIDIA CORPORATION nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
import tritonclient.http as httpclient
import tritonclient.grpc as grpcclient
import numpy
import pytest
import unittest
import os
import shutil
import subprocess
import time
import re
from pathlib import Path
import datetime
import json
import google.protobuf.text_format

def parse_timestamp(timestamp):
    hours, minutes, seconds = timestamp.split(':')
    hours = int(hours)
    minutes = int(minutes)
    seconds = float(seconds)
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


module_directory = os.path.split(os.path.abspath(__file__))[0]

test_model_directory = os.path.abspath(os.path.join(module_directory, "log_models"))


test_logs_directory = os.path.abspath(
    os.path.join(module_directory, "log_format_test_logs")
)


shutil.rmtree(test_logs_directory, ignore_errors=True)

os.makedirs(test_logs_directory)


import re

# Sample ASCII table
ascii_table = """
+--------+---------+----------------------------------------------------------------------------------------------------------------------------------+
| Model  | Version | Status                                                                                                                           |
+--------+---------+----------------------------------------------------------------------------------------------------------------------------------+
| simple | 1       | UNAVAILABLE: Not found: unable to load shared library: /opt/tritonserver/backends/onnxruntime/libtriton_onnxruntime.so: undefined symbol: TRITONSERVER_LogServerMessage |
+--------+---------+----------------------------------------------------------------------------------------------------------------------------------+
"""


# I0516 17:33:33.476093 2814 cache_manager.cc:480] "Create CacheManager with cache_dir: '/opt/tritonserver/caches'"

# import re

# Sample log entry
# log_entry = "#I0516 17:33:33.476093 2814 cache_manager.cc:480] \"Create CacheManager with cache_dir: '/opt/tritonserver/caches'\""


# Regular expression pattern to capture the headers and rows
table_regex = re.compile(
    r'\+[-+]+\+\n'  # Match the top border
    r'\| (?P<header>.*?) \|\n'  # Capture the header
    r'\+[-+]+\+\n'  # Match the header border
    r'(?P<rows>(?:\| .*? \|\n)*)'  # Capture the rows
    r'\+[-+]+\+',  # Match the bottom border
    re.DOTALL  # Enable dot to match newlines
)

# Regular expression pattern
default_pattern = r'(?P<level>\w)(?P<month>\d{2})(?P<day>\d{2}) (?P<timestamp>\d{2}:\d{2}:\d{2}\.\d{6}) (?P<pid>\d+) (?P<file>[\w\.]+):(?P<line>\d+)] (?P<message>.*)'

# Compile the regex pattern
default_regex = re.compile(default_pattern, re.DOTALL)

LEVELS = set({"E", "W", "I"})

FORMATS = [
    ("default", default_regex),
    ("ISO8601", ""),
    ("default_unescaped", ""),
    ("ISO8601_unescaped", ""),
]

IDS = ["default", "ISO8601", "default_unescaped", "ISO8601_unescaped"]

validators = {}

def validator(func):
    validators[func.__name__.replace('validate_','')] = func
    return func

@validator
def validate_level(level):
    assert level in LEVELS

@validator
def validate_month(month):
    assert month.isdigit()
    month = int(month)
    assert month >= 1 and month <= 12

@validator
def validate_day(day):
    assert day.isdigit()
    day = int(day)
    assert day >= 1 and day <= 31

@validator
def validate_timestamp(timestamp):
    parse_timestamp(timestamp)

@validator
def validate_pid(pid):
    assert pid.isdigit()

@validator
def validate_file(file_):
    assert Path(file_).name is not None

@validator
def validate_line(line):
    assert line.isdigit()

def validate_table(table):
    header = table.group("header").strip().split('|')
    rows = table.group("rows").strip().split('\n')

    # Process each row
    parsed_rows = []
    for row in rows:
        if row:
            row_data = [r.strip() for r in row.split('|')[1:-1]]
            parsed_rows.append(row_data)
   
    for row in parsed_rows:
        assert len(row)==len(header)
    
@validator
def validate_message(message):
    heading, obj = message.split('\n',1)
    if heading:
        try:
            json.loads(heading)
        except json.JSONDecodeError as e:
            raise Exception(f"{e} First line of message in log record is not a valid JSON string")
        except Exception as e:
            raise type(e)(f"{e} First line of message in log record is not a valid JSON string")
    if len(obj):
        obj = obj.strip()       
        match = table_regex.search(obj)
        if match:
            validate_table(match)
        else:
            google.protobuf.text_format.Parse(obj,grpcclient.model_config_pb2.ModelConfig())

class TestLogFormat:
    @pytest.fixture(autouse=True)
    def setup(self, request):
        test_case_name = request.node.name
        self._server_options = {}
        self._server_options["log-verbose"] = 256
        self._server_options["log-info"] = 1
        self._server_options["log-error"] = 1
        self._server_options["log-warning"] = 1
        self._server_options["log-format"] = "default"
        self._server_options["model-repository"] = os.path.abspath(
            os.path.join(module_directory, "log_models")
        )
        self._server_process = None
        self._server_options["log-file"] = os.path.join(
            test_logs_directory, test_case_name + ".server.log"
        )

    def _launch_server(self, unescaped=None):
        cmd = ["tritonserver"]

        for key, value in self._server_options.items():
            cmd.append(f"--{key}={value}")

        env = os.environ.copy()

        if unescaped:
            env["TRITON_SERVER_ESCAPE_LOG_MESSSAGES"] = "FALSE"
        elif unescaped is not None:
            env["TRITON_SERVER_ESCAPE_LOG_MESSSAGES"] = "TRUE"

        self._server_process = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        wait_time = 5

        while wait_time and not os.path.exists(self._server_options["log-file"]):
            time.sleep(1)
            wait_time -= 1

        if not os.path.exists(self._server_options["log-file"]):
            raise Exception("Log not found")

    def validate_log_record(self, record, format_regex):
        match = format_regex.search(record)
        if match:
            for field, value in match.groupdict().items():
                if field in validators:
                    try:
                        validators[field](value)
                    except Exception as e:
                        raise type(e)(f"{e}\nInvalid {field}: '{match.group(field)}' in log record '{record}'")

        else:
            raise Exception("Invalid log line")

    def verify_log_format(self, file_path, format_regex):
        log_records = []
        with open(file_path, "rt") as file_:
            current_log_record = []
            for line in file_:
                match = format_regex.search(line)
                if match:
                    if current_log_record:
                        log_records.append(current_log_record)
                    current_log_record = [line]
                else:
                    current_log_record.append(line)
        log_records.append(current_log_record)
        log_records = ["".join(log_record_lines) for log_record_lines in log_records]
        for log_record in log_records:
            self.validate_log_record(log_record, format_regex)

    @pytest.mark.parametrize(
        "log_format,format_regex",
        FORMATS,
        ids=IDS,
    )
    def test_log_format(self, log_format, format_regex):
        self._server_options["log-format"] = log_format.replace("_unescaped", "")
        self._launch_server(unescaped=True if "_unescaped" in log_format else False)
        time.sleep(1)
        self._server_process.kill()
        return_code = self._server_process.wait()
        if isinstance(format_regex, str):
            return
        self.verify_log_format(self._server_options["log-file"], format_regex)

    def foo_test_injection(self):
        try:
            triton_client = httpclient.InferenceServerClient(
                url="localhost:8000", verbose=True
            )
        except Exception as e:
            print("context creation failed: " + str(e))
            sys.exit(1)

        input_name = "'nothing_wrong'\nI0205 18:34:18.707423 1 [file.cc:123] THIS ENTRY WAS INJECTED\nI0205 18:34:18.707461 1 [http_server.cc:3570] [request id: <id_unknown>] Infer failed: [request id: <id_unknown>] input 'nothing_wrong"

        input_data = numpy.random.randn(1, 3).astype(numpy.float32)
        input_tensor = httpclient.InferInput(input_name, input_data.shape, "FP32")
        input_tensor.set_data_from_numpy(input_data)

        triton_client.infer(model_name="simple", inputs=[input_tensor])
