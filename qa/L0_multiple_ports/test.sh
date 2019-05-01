#!/bin/bash
# Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
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

MULTI_PORT_TESTS_PY=multi_port_tests.py

CLIENT_LOG="./client.log"
SERVER_LOG="./inference_server.log"

DATADIR=`pwd`/models
SERVER=/opt/tensorrtserver/bin/trtserver
source ../common/util.sh

SP_ARR=(8008 8009 8010 8011 -1 8004 8004 8004 8004 -1 -1 -1)
HP_ARR=(8008 8010 8010 8009 8005 -1 8005 8005 -1 8004 -1 -1)
PP_ARR=(8008 8011 8011 8010 8005 8005 -1 8006 -1 -1 8004 -1)
IP_ARR=(8008 8011 8008 8008 8006 8006 8006 -1 -1 -1 -1 8004)
len=${#SP_ARR[@]}
rm -f $CLIENT_LOG $SERVER_LOG

RET=0
# HTTP + GRPC w/o Interleaved
for (( n=0; n<$len; n++ )) ; do
  SERVER_ARGS_ADD_GRPC="--grpc-status-port ${SP_ARR[n]} --grpc-health-port ${HP_ARR[n]} \
    --grpc-profile-port ${PP_ARR[n]} --grpc-infer-port ${IP_ARR[n]} --allow-grpc 1"
  SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_GRPC"

  run_server_nowait
  sleep 10
  if [ "$SERVER_PID" == "0" ]; then
      echo -e "\n***\n*** Failed to start $SERVER\n***"
      cat $SERVER_LOG
      exit 1
  fi

  set +e
  python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -sp ${SP_ARR[n]} -hp ${HP_ARR[n]} -pp ${PP_ARR[n]} -ip ${IP_ARR[n]} -i grpc
  if [ $? -ne 0 ]; then
      RET=1
  fi
  set -e

  kill $SERVER_PID
  wait $SERVER_PID

  SERVER_ARGS_ADD_HTTP="--http-status-port ${SP_ARR[n]} --http-health-port ${HP_ARR[n]} \
    --http-profile-port ${PP_ARR[n]} --http-infer-port ${IP_ARR[n]} --allow-http 1"
  SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"

  run_server_nowait
  sleep 10
  if [ "$SERVER_PID" == "0" ]; then
      echo -e "\n***\n*** Failed to start $SERVER\n***"
      cat $SERVER_LOG
      exit 1
  fi

  set +e
  python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -sp ${SP_ARR[n]} -hp ${HP_ARR[n]} -pp ${PP_ARR[n]} -ip ${IP_ARR[n]} -i http
  if [ $? -ne 0 ]; then
      RET=1
  fi
  set -e

  kill $SERVER_PID
  wait $SERVER_PID
done

# HTTP + GRPC w/ Interleaved
P=(8005 -1)
for (( i=0; i<2; i++ )) ; do
  for (( n=0; n<$len; n++ )) ; do
    SERVER_ARGS_ADD_GRPC="--grpc-port ${P[i]} --grpc-status-port ${SP_ARR[n]} --grpc-health-port ${HP_ARR[n]} \
      --grpc-profile-port ${PP_ARR[n]} --grpc-infer-port ${IP_ARR[n]} --allow-grpc 1"
    SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_GRPC"

    run_server_nowait
    sleep 10
    if [ "$SERVER_PID" == "0" ]; then
        echo -e "\n***\n*** Failed to start $SERVER\n***"
        cat $SERVER_LOG
        exit 1
    fi

    set +e
    python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -p 8005 -sp ${SP_ARR[n]} -hp ${HP_ARR[n]} -pp ${PP_ARR[n]} -ip ${IP_ARR[n]} -i grpc
    if [ $? -ne 0 ]; then
        RET=1
    fi
    set -e

    kill $SERVER_PID
    wait $SERVER_PID

    SERVER_ARGS_ADD_HTTP="--http-port ${P[i]} --http-status-port ${SP_ARR[n]} --http-health-port ${HP_ARR[n]} \
      --http-profile-port ${PP_ARR[n]} --http-infer-port ${IP_ARR[n]} --allow-http 1"
    SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"

    run_server_nowait
    sleep 10
    if [ "$SERVER_PID" == "0" ]; then
        echo -e "\n***\n*** Failed to start $SERVER\n***"
        cat $SERVER_LOG
        exit 1
    fi

    set +e
    python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -p 8005 -sp ${SP_ARR[n]} -hp ${HP_ARR[n]} -pp ${PP_ARR[n]} -ip ${IP_ARR[n]}
    if [ $? -ne 0 ]; then
        RET=1
    fi
    set -e

    kill $SERVER_PID
    wait $SERVER_PID
  done
done

# CUSTOM CASES
# set http ports to -1 after setting them to 8007
SERVER_ARGS_ADD_HTTP="--http-status-port 8007 --http-health-port 8007 \
  --http-profile-port 8007 --http-infer-port 8007 --http-port -1 --allow-http 1"
SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"
run_server_nowait
sleep 10
if [ "$SERVER_PID" == "0" ]; then
    echo -e "\n***\n*** Failed to start $SERVER\n***"
    cat $SERVER_LOG
    exit 1
fi
set +e
python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -p -1 -sp 8007 -hp 8007 -pp 8007 -ip 8007
if [ $? -ne 0 ]; then
    RET=1
fi
set -e
kill $SERVER_PID
wait $SERVER_PID
# allow overrules - grpc still works
SERVER_ARGS_ADD_HTTP="--http-status-port 8007 --http-health-port 8007 \
  --http-profile-port 8007 --http-infer-port 8007 --http-port -1 --allow-http 0"
SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"
run_server_nowait
sleep 10
if [ "$SERVER_PID" == "0" ]; then
    echo -e "\n***\n*** Failed to start $SERVER\n***"
    cat $SERVER_LOG
    exit 1
fi
set +e
python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -p -1 -sp 8007 -hp 8007 -pp 8007 -ip 8007
if [ $? -ne 0 ]; then
    RET=1
fi
set -e
kill $SERVER_PID
wait $SERVER_PID
# overlap with grpc default
SERVER_ARGS_ADD_HTTP="--http-status-port 8001 --http-health-port 8007 \
  --http-profile-port 8007 --http-infer-port 8007"
SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"
run_server_nowait
sleep 10
if [ "$SERVER_PID" != "0" ]; then
    echo -e "\n***\n*** Should not have started $SERVER\n***"
    cat $SERVER_LOG
    exit 1
fi
set +e
python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -sp 8001 -hp 8007 -pp 8007 -ip 8007
if [ $? -ne 0 ]; then
    RET=1
fi
set -e
# overlap with metrics default
SERVER_ARGS_ADD_HTTP="--http-status-port 8002 --http-health-port 8007 \
  --http-profile-port 8007 --http-infer-port 8007"
SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"
run_server_nowait
sleep 10
if [ "$SERVER_PID" != "0" ]; then
    echo -e "\n***\n*** Should not have started $SERVER\n***"
    cat $SERVER_LOG
    exit 1
fi
# disable metrics - no overlap with metrics default
SERVER_ARGS_ADD_HTTP="--http-status-port 8002 --http-health-port 8007 \
  --http-profile-port 8007 --http-infer-port 8007 --allow_metrics 0"
SERVER_ARGS="--model-store=$DATADIR $SERVER_ARGS_ADD_HTTP"
run_server_nowait
sleep 10
if [ "$SERVER_PID" == "0" ]; then
    echo -e "\n***\n*** Failed to start $SERVER\n***"
    cat $SERVER_LOG
    exit 1
fi
set +e
python $MULTI_PORT_TESTS_PY -v >>$CLIENT_LOG 2>&1 -sp 8002 -hp 8007 -pp 8007 -ip 8007
if [ $? -ne 0 ]; then
    RET=1
fi
set -e
kill $SERVER_PID
wait $SERVER_PID

exit $RET
