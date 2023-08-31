#!/bin/bash
# Copyright (c) 2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

REPO_VERSION=${NVIDIA_TRITON_SERVER_VERSION}
if [ "$#" -ge 1 ]; then
    REPO_VERSION=$1
fi
if [ -z "$REPO_VERSION" ]; then
    echo -e "Repository version must be specified"
    echo -e "\n***\n*** Test Failed\n***"
    exit 1
fi

export CUDA_VISIBLE_DEVICES=0

DATADIR=${DATADIR:="/data/inferenceserver/${REPO_VERSION}"}
SERVER=/opt/tritonserver/bin/tritonserver
SERVER_ARGS="--model-repository=`pwd`/models --exit-timeout-secs=120"
SERVER_LOG="./inference_server.log"
source ../common/util.sh

rm -fr models && mkdir models
cp -r $DATADIR/qa_identity_model_repository/plan_compatible_zero_1_float32 models/.
rm -f *.log

if [ `ps | grep -c "tritonserver"` != "0" ]; then
    echo -e "Tritonserver already running"
    echo -e `ps | grep tritonserver`
    exit 1
fi

run_server
if [ "$SERVER_PID" != "0" ]; then
    cat $SERVER_LOG
    echo -e "\n***\n*** FAILED: unexpected server start (version compatibility disabled): $SERVER\n***" >> $CLIENT_LOG
    kill $SERVER_PID
    wait $SERVER_PID
    exit 1
fi

SERVER_ARGS="--model-repository=`pwd`/models --exit-timeout-secs=120 --backend-config=tensorrt,version-compatible=true"

run_server
if [ "$SERVER_PID" == "0" ]; then
    cat $SERVER_LOG
    echo -e "\n***\n*** FAILED: unsuccessful server start (version compatibility enabled): $SERVER\n***"
    exit 1
fi

echo -e "\n***\n*** Test Passed\n***"
