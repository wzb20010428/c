# Copyright 2021, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
sys.path.append("../common")

import numpy as np
import multiprocessing
import time
import test_util as tu
import argparse
import tritongrpcclient as grpcclient
from tritonclientutils import np_to_triton_dtype


def crashing_client(model_name, dtype, triton_client, tensor_shape=(1,)):
    in0 = np.random.random(tensor_shape).astype(dtype)
    inputs = [
        grpcclient.InferInput("INPUT0", tensor_shape,
                              np_to_triton_dtype(dtype)),
    ]
    inputs[0].set_data_from_numpy(in0)

    # Run in a loop so that it is guaranteed that
    # the inference will not have completed when being terminated.
    while True:
        results = triton_client.infer(model_name, inputs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-t',
                        '--trial',
                        type=str,
                        required=True,
                        help='Set trial for the crashing client')
    FLAGS = parser.parse_args()

    trial = FLAGS.trial
    dtype = np.float32
    model_name = tu.get_zero_model_name(trial, 1, dtype)

    triton_client = grpcclient.InferenceServerClient(url="localhost:8001",
                                                     verbose=True)

    p = multiprocessing.Process(target=crashing_client,
                                name="crashing_client",
                                args=(
                                    model_name,
                                    dtype,
                                    triton_client,
                                ))

    p.start()

    # Terminate the client after 5 seconds
    time.sleep(5)
    p.terminate()

    # Cleanup
    p.join()

    if not triton_client.is_server_live():
        sys.exit(1)

    sys.exit(0)
