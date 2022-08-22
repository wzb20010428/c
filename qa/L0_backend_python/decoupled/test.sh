# Copyright (c) 2022, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

CLIENT_PY=./decoupled_test.py
CLIENT_LOG="./client.log"
EXPECTED_NUM_TESTS="4"
TEST_RESULT_FILE='test_results.txt'
TRITON_DIR=${TRITON_DIR:="/opt/tritonserver"}
SERVER=${TRITON_DIR}/bin/tritonserver
BACKEND_DIR=${TRITON_DIR}/backends
SERVER_ARGS="--model-repository=`pwd`/models --backend-directory=${BACKEND_DIR} --log-verbose=1"
SERVER_LOG="./inference_server.log"

RET=0
source ../../common/util.sh

rm -fr *.log
mkdir -p models/identity_fp32/1/
cp ../../python_models/identity_fp32/model.py models/identity_fp32/1/
cp ../../python_models/identity_fp32/config.pbtxt models/identity_fp32/

mkdir -p models/dlpack_add_sub/1/
cp ../../python_models/dlpack_add_sub/model.py models/dlpack_add_sub/1/
cp ../../python_models/dlpack_add_sub/config.pbtxt models/dlpack_add_sub/

mkdir -p models/dlpack_add_sub_logging/1/
cp ../../python_models/dlpack_add_sub_logging/model.py models/dlpack_add_sub_logging/1/
cp ../../python_models/dlpack_add_sub_logging/config.pbtxt models/dlpack_add_sub_logging/

function verify_log_counts () {
  non_verbose_expected=$1
  verbose_expected=$2

  if [ `grep -c "Specific Msg!" ./server.log` -lt $non_verbose_expected ]; then
    echo -e "\n***\n*** Test Failed: Specific Msg Count Incorrect\n***"
    RET=1
  fi
  if [ `grep -c "Info Msg!" ./server.log` -lt $non_verbose_expected ]; then
    echo -e "\n***\n*** Test Failed: Info Msg Count Incorrect\n***"
    RET=1
  fi
  if [ `grep -c "Warning Msg!" ./server.log` -lt $non_verbose_expected ]; then
    echo -e "\n***\n*** Test Failed: Warning Msg Count Incorrect\n***"
    RET=1
  fi
  if [ `grep -c "Error Msg!" ./server.log` -lt $non_verbose_expected ]; then
    echo -e "\n***\n*** Test Failed: Error Msg Count Incorrect\n***"
    RET=1
  fi
  if [ `grep -c "Verbose Msg!" ./server.log` != $verbose_expected ]; then
    echo -e "\n***\n*** Test Failed: Verbose Msg Count Incorrect\n***"
    RET=1
  fi
}

run_server
if [ "$SERVER_PID" == "0" ]; then
    echo -e "\n***\n*** Failed to start $SERVER\n***"
    cat $SERVER_LOG
    RET=1
fi

set +e
python3 $CLIENT_PY > $CLIENT_LOG 2>&1

if [ $? -ne 0 ]; then
    echo -e "\n***\n*** decoupled test FAILED. \n***"
    RET=1
else
    check_test_results $TEST_RESULT_FILE $EXPECTED_NUM_TESTS
    if [ $? -ne 0 ]; then
        cat $CLIENT_LOG
        echo -e "\n***\n*** Test Result Verification Failed\n***"
        RET=1
    fi
fi
set -e

kill $SERVER_PID
wait $SERVER_PID

verify_log_counts 3 0

if [ $RET -eq 1 ]; then
    cat $CLIENT_LOG
    cat $SERVER_LOG
    echo -e "\n***\n*** Decoupled test FAILED. \n***"
else
    echo -e "\n***\n*** Decoupled test PASSED. \n***"
fi

exit $RET
