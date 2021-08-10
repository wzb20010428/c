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

import argparse
from builtins import range
from builtins import str
from future.utils import iteritems
import os
import time
import math
import threading
import traceback
import numpy as np
import test_util as tu
from functools import partial
import tritongrpcclient as grpcclient
from tritonclientutils import np_to_triton_dtype

if sys.version_info >= (3, 0):
    import queue
else:
    import Queue as queue

FLAGS = None
CORRELATION_ID_BLOCK_SIZE = 100
DEFAULT_TIMEOUT_MS = 9000
SEQUENCE_LENGTH_MEAN = 16
SEQUENCE_LENGTH_STDEV = 8
BACKENDS = os.environ.get('BACKENDS', "graphdef savedmodel onnx plan")

_thread_exceptions = []
_thread_exceptions_mutex = threading.Lock()


class UserData:

    def __init__(self):
        self._completed_requests = queue.Queue()


# Callback function used for async_stream_infer()
def completion_callback(user_data, result, error):
    # passing error raise and handling out
    user_data._completed_requests.put((result, error))


class TimeoutException(Exception):
    pass


def check_sequence_async(client_metadata,
                         trial,
                         model_name,
                         input_dtype,
                         steps,
                         timeout_ms=DEFAULT_TIMEOUT_MS,
                         batch_size=1,
                         sequence_name="<unknown>",
                         tensor_shape=(1,),
                         input_name="INPUT",
                         output_name="OUTPUT"):
    """Perform sequence of inferences using async run. The 'steps' holds
    a list of tuples, one for each inference with format:

    (flag_str, value, expected_result, delay_ms)

    """
    if (("savedmodel" not in trial) and ("graphdef" not in trial) and
        ("custom" not in trial) and ("onnx" not in trial) and
        ("libtorch" not in trial) and ("plan" not in trial)):
        assert False, "unknown trial type: " + trial

    if "nobatch" not in trial:
        tensor_shape = (batch_size,) + tensor_shape
    if "libtorch" in trial:
        input_name = "INPUT__0"
        output_name = "OUTPUT__0"

    triton_client = client_metadata[0]
    sequence_id = client_metadata[1]

    # Execute the sequence of inference...
    seq_start_ms = int(round(time.time() * 1000))
    user_data = UserData()
    # Ensure there is no running stream
    triton_client.stop_stream()
    triton_client.start_stream(partial(completion_callback, user_data))

    sent_count = 0
    for flag_str, value, expected_result, delay_ms in steps:
        seq_start = False
        seq_end = False
        if flag_str is not None:
            seq_start = ("start" in flag_str)
            seq_end = ("end" in flag_str)

        if input_dtype == np.object_:
            in0 = np.full(tensor_shape, value, dtype=np.int32)
            in0n = np.array([str(x) for x in in0.reshape(in0.size)],
                            dtype=object)
            in0 = in0n.reshape(tensor_shape)
        else:
            in0 = np.full(tensor_shape, value, dtype=input_dtype)

        inputs = [
            grpcclient.InferInput(input_name, tensor_shape,
                                  np_to_triton_dtype(input_dtype)),
        ]
        inputs[0].set_data_from_numpy(in0)

        triton_client.async_stream_infer(model_name,
                                         inputs,
                                         sequence_id=sequence_id,
                                         sequence_start=seq_start,
                                         sequence_end=seq_end)
        sent_count += 1

        if delay_ms is not None:
            time.sleep(delay_ms / 1000.0)

    # Process the results in order that they were sent
    result = None
    processed_count = 0
    while processed_count < sent_count:
        (results, error) = user_data._completed_requests.get()
        if error is not None:
            raise error

        (_, value, expected, _) = steps[processed_count]
        processed_count += 1
        if timeout_ms != None:
            now_ms = int(round(time.time() * 1000))
            if (now_ms - seq_start_ms) > timeout_ms:
                raise TimeoutException(
                    "Timeout expired for {}".format(sequence_name))

        result = results.as_numpy(
            output_name)[0] if "nobatch" in trial else results.as_numpy(
                output_name)[0][0]
        if FLAGS.verbose:
            print("{} {}: + {} = {}".format(sequence_name, sequence_id, value,
                                            result))

        if expected is not None:
            if input_dtype == np.object_:
                assert int(
                    result
                ) == expected, "{}: expected result {}, got {} {} {}".format(
                    sequence_name, expected, int(result), trial, model_name)
            else:
                assert result == expected, "{}: expected result {}, got {} {} {}".format(
                    sequence_name, expected, result, trial, model_name)
    triton_client.stop_stream()


def get_datatype(trial):
    # Get the datatype to use based on what models are available (see test.sh)
    if ("plan" in trial) or ("savedmodel" in trial):
        return np.float32
    if "graphdef" in trial:
        return np.dtype(object)
    return np.int32


def get_expected_result(expected_result, value, trial, flag_str=None):
    # Adjust the expected_result for models that
    # couldn't implement the full accumulator. See
    # qa/common/gen_qa_sequence_models.py for more
    # information.
    if (("nobatch" not in trial and
         ("custom" not in trial)) or ("graphdef" in trial) or
        ("plan" in trial) or ("onnx" in trial)) or ("libtorch" in trial):
        expected_result = value
        if (flag_str is not None) and ("start" in flag_str):
            expected_result += 1
    return expected_result


def get_trial(is_sequence=True):
    # Randomly pick one trial for each thread
    if is_sequence:
        _trials = ()
        for backend in BACKENDS.split(' '):
            if (backend != "libtorch") and (backend != 'savedmodel'):
                _trials += (backend + "_nobatch",)
            _trials += (backend,)
        return np.random.choice(_trials)
    else:
        _trials = ()
        for backend in BACKENDS.split(' '):
            if (backend != "libtorch"):
                _trials += (backend + "_nobatch",)
        return np.random.choice(_trials)


def sequence_valid(client_metadata, rng, trial, model_name, dtype, len_mean,
                   len_stddev, sequence_name):
    # Create a variable length sequence with "start" and "end" flags.
    seqlen = max(1, int(rng.normal(len_mean, len_stddev)))
    print("{} {}: valid seqlen = {}".format(sequence_name, client_metadata[1],
                                            seqlen))

    values = rng.randint(0, 1024 * 1024, size=seqlen).astype(dtype)

    steps = []
    expected_result = 0

    for idx, step in enumerate(range(seqlen)):
        flags = ""
        if idx == 0:
            flags += ",start"
        if idx == (seqlen - 1):
            flags += ",end"

        val = values[idx]
        delay_ms = None
        expected_result += val
        expected_result = get_expected_result(expected_result, val, trial,
                                              flags)

        # (flag_str, value, expected_result, delay_ms)
        steps.append((flags, val, expected_result, delay_ms),)

    check_sequence_async(client_metadata,
                         trial,
                         model_name,
                         dtype,
                         steps,
                         sequence_name=sequence_name)


def sequence_valid_valid(client_metadata, rng, trial, model_name, dtype,
                         len_mean, len_stddev, sequence_name):
    # Create two variable length sequences with "start" and "end"
    # flags, where both sequences use the same correlation ID and are
    # sent back-to-back.
    seqlen = [
        max(1, int(rng.normal(len_mean, len_stddev))),
        max(1, int(rng.normal(len_mean, len_stddev)))
    ]
    print("{} {}: valid-valid seqlen[0] = {}, seqlen[1] = {}".format(
        sequence_name, client_metadata[1], seqlen[0], seqlen[1]))

    values = [
        rng.randint(0, 1024 * 1024, size=seqlen[0]).astype(dtype),
        rng.randint(0, 1024 * 1024, size=seqlen[1]).astype(dtype)
    ]

    for p in [0, 1]:
        steps = []
        expected_result = 0

        for idx, step in enumerate(range(seqlen[p])):
            flags = ""
            if idx == 0:
                flags += ",start"
            if idx == (seqlen[p] - 1):
                flags += ",end"

            val = values[p][idx]
            delay_ms = None
            expected_result += val
            expected_result = get_expected_result(expected_result, val, trial,
                                                  flags)

            # (flag_str, value, expected_result, delay_ms)
            steps.append((flags, val, expected_result, delay_ms),)

    check_sequence_async(client_metadata,
                         trial,
                         model_name,
                         dtype,
                         steps,
                         sequence_name=sequence_name)


def sequence_valid_no_end(client_metadata, rng, trial, model_name, dtype,
                          len_mean, len_stddev, sequence_name):
    # Create two variable length sequences, the first with "start" and
    # "end" flags and the second with no "end" flag, where both
    # sequences use the same correlation ID and are sent back-to-back.
    seqlen = [
        max(1, int(rng.normal(len_mean, len_stddev))),
        max(1, int(rng.normal(len_mean, len_stddev)))
    ]
    print("{} {}: valid-no-end seqlen[0] = {}, seqlen[1] = {}".format(
        sequence_name, client_metadata[1], seqlen[0], seqlen[1]))

    values = [
        rng.randint(0, 1024 * 1024, size=seqlen[0]).astype(dtype),
        rng.randint(0, 1024 * 1024, size=seqlen[1]).astype(dtype)
    ]

    for p in [0, 1]:
        steps = []
        expected_result = 0

        for idx, step in enumerate(range(seqlen[p])):
            flags = ""
            if idx == 0:
                flags += ",start"
            if (p == 0) and (idx == (seqlen[p] - 1)):
                flags += ",end"

            val = values[p][idx]
            delay_ms = None
            expected_result += val
            expected_result = get_expected_result(expected_result, val, trial,
                                                  flags)

            # (flag_str, value, expected_result, delay_ms)
            steps.append((flags, val, expected_result, delay_ms),)

    check_sequence_async(client_metadata,
                         trial,
                         model_name,
                         dtype,
                         steps,
                         sequence_name=sequence_name)


def sequence_no_start(client_metadata, rng, trial, model_name, dtype,
                      sequence_name):
    # Create a sequence without a "start" flag. Sequence should get an
    # error from the server.
    seqlen = 1
    print("{} {}: no-start seqlen = {}".format(sequence_name,
                                               client_metadata[1], seqlen))

    values = rng.randint(0, 1024 * 1024, size=seqlen).astype(dtype)

    steps = []

    for idx, step in enumerate(range(seqlen)):
        flags = None
        val = values[idx]
        delay_ms = None

        # (flag_str, value, expected_result, delay_ms)
        steps.append((flags, val, None, delay_ms),)

    try:
        check_sequence_async(client_metadata,
                             trial,
                             model_name,
                             dtype,
                             steps,
                             sequence_name=sequence_name)
        assert False, "expected inference failure from missing START flag"
    except Exception as ex:
        if "must specify the START flag" not in ex.message():
            raise


def sequence_no_end(client_metadata, rng, trial, model_name, dtype, len_mean,
                    len_stddev, sequence_name):
    # Create a variable length sequence with "start" flag but that
    # never ends. The sequence should be aborted by the server and its
    # slot reused for another sequence.
    seqlen = max(1, int(rng.normal(len_mean, len_stddev)))
    print("{} {}: no-end seqlen = {}".format(sequence_name, client_metadata[1],
                                             seqlen))

    values = rng.randint(0, 1024 * 1024, size=seqlen).astype(dtype)

    steps = []
    expected_result = 0

    for idx, step in enumerate(range(seqlen)):
        flags = ""
        if idx == 0:
            flags = "start"

        val = values[idx]
        delay_ms = None
        expected_result += val
        expected_result = get_expected_result(expected_result, val, trial,
                                              flags)

        # (flag_str, value, expected_result, delay_ms)
        steps.append((flags, val, expected_result, delay_ms),)

    check_sequence_async(client_metadata,
                         trial,
                         model_name,
                         dtype,
                         steps,
                         sequence_name=sequence_name)


def timeout_client(client_metadata,
                   name,
                   input_dtype=np.float32,
                   input_name="INPUT0"):
    trial = get_trial(is_sequence=False)
    model_name = tu.get_zero_model_name(trial, 1, input_dtype)
    triton_client = client_metadata[0]
    if "librotch" in trial:
        input_name = "INPUT__0"

    tensor_shape = (math.trunc(1 * (1024 * 1024 * 1024) //
                               np.dtype(input_dtype).itemsize),)
    in0 = np.random.random(tensor_shape).astype(input_dtype)
    inputs = [
        grpcclient.InferInput(input_name, tensor_shape,
                              np_to_triton_dtype(input_dtype)),
    ]
    inputs[0].set_data_from_numpy(in0)

    # Expect an exception for small timeout values.
    try:
        results = triton_client.infer(model_name, inputs, client_timeout=0.1)
        assert False, "expected inference failure from deadline exceeded"
    except Exception as ex:
        if "Deadline Exceeded" not in ex.message():
            assert False, "timeout_client failed {}".format(name)


def resnet_model_request(name):
    image_client = "../clients/image_client.py"
    image = "../images/vulture.jpeg"
    model_name = "resnet_v1_50_graphdef_def"
    resnet_result = "resnet_{}.log".format(name)

    os.system("{} -m {} -s VGG -c 1 -b 1 {} > {}".format(
        image_client, model_name, image, resnet_result))
    with open(resnet_result) as f:
        if "VULTURE" not in f.read():
            assert False, "resnet_model_request failed"


def crashing_client(name):
    trial = get_trial(is_sequence=False)

    # Client will be terminated after 5 seconds
    crashing_client = "crashing_client.py"
    crashing_client_log = "crashing_{}.log".format(name)
    if os.system("python {} -t {} >> {}".format(crashing_client, trial,
                                                crashing_client_log)):
        assert False, "crashing_client failed {}".format(name)


def stress_thread(name, seed, test_duration, correlation_id_base):
    # Thread responsible for generating sequences of inference
    # requests.
    global _thread_exceptions

    print("Starting thread {} with seed {}".format(name, seed))
    rng = np.random.RandomState(seed)

    client_metadata_list = []
    start_time = time.time()

    try:
        # Must use streaming GRPC context to ensure each sequences'
        # requests are received in order. Create 2 common-use contexts
        # with different correlation IDs that are used for most
        # inference requests. Also create some rare-use contexts that
        # are used to make requests with rarely-used correlation IDs.
        #
        # Need to remember the last choice for each context since we
        # don't want some choices to follow others since that gives
        # results not expected. See below for details.
        common_cnt = 2
        rare_cnt = 8
        last_choices = []

        for c in range(common_cnt + rare_cnt):
            client_metadata_list.append(
                (grpcclient.InferenceServerClient("localhost:8001",
                                                  verbose=FLAGS.verbose),
                 correlation_id_base + c))
            last_choices.append(None)

        rare_idx = 0
        while time.time() - start_time < test_duration:
            trial = get_trial()
            dtype = get_datatype(trial)
            model_name = tu.get_sequence_model_name(trial, dtype)
            # Common or rare context?
            if rng.rand() < 0.1:
                # Rare context...
                choice = rng.rand()
                client_idx = common_cnt + rare_idx

                # Send a no-end, valid-no-end or valid-valid
                # sequence... because it is a rare context this should
                # exercise the idle sequence path of the sequence
                # scheduler
                if choice < 0.33:
                    sequence_no_end(client_metadata_list[client_idx],
                                    rng,
                                    trial,
                                    model_name,
                                    dtype,
                                    SEQUENCE_LENGTH_MEAN,
                                    SEQUENCE_LENGTH_STDEV,
                                    sequence_name=name)
                    last_choices[client_idx] = "no-end"
                elif choice < 0.66:
                    sequence_valid_no_end(client_metadata_list[client_idx],
                                          rng,
                                          trial,
                                          model_name,
                                          dtype,
                                          SEQUENCE_LENGTH_MEAN,
                                          SEQUENCE_LENGTH_STDEV,
                                          sequence_name=name)
                    last_choices[client_idx] = "valid-no-end"
                else:
                    sequence_valid_valid(client_metadata_list[client_idx],
                                         rng,
                                         trial,
                                         model_name,
                                         dtype,
                                         SEQUENCE_LENGTH_MEAN,
                                         SEQUENCE_LENGTH_STDEV,
                                         sequence_name=name)
                    last_choices[client_idx] = "valid-valid"

                rare_idx = (rare_idx + 1) % rare_cnt
            elif rng.rand() < 0.6:
                # Common context...
                client_idx = 0
                client_metadata = client_metadata_list[client_idx]
                last_choice = last_choices[client_idx]

                choice = rng.rand()

                # no-start cannot follow no-end since the server will
                # just assume that the no-start is a continuation of
                # the no-end sequence instead of being a sequence
                # missing start flag.
                if ((last_choice != "no-end") and
                    (last_choice != "valid-no-end") and (choice < 0.01)):
                    sequence_no_start(client_metadata,
                                      rng,
                                      trial,
                                      model_name,
                                      dtype,
                                      sequence_name=name)
                    last_choices[client_idx] = "no-start"
                elif choice < 0.05:
                    sequence_no_end(client_metadata,
                                    rng,
                                    trial,
                                    model_name,
                                    dtype,
                                    SEQUENCE_LENGTH_MEAN,
                                    SEQUENCE_LENGTH_STDEV,
                                    sequence_name=name)
                    last_choices[client_idx] = "no-end"
                elif choice < 0.10:
                    sequence_valid_no_end(client_metadata,
                                          rng,
                                          trial,
                                          model_name,
                                          dtype,
                                          SEQUENCE_LENGTH_MEAN,
                                          SEQUENCE_LENGTH_STDEV,
                                          sequence_name=name)
                    last_choices[client_idx] = "valid-no-end"
                elif choice < 0.15:
                    sequence_valid_valid(client_metadata,
                                         rng,
                                         trial,
                                         model_name,
                                         dtype,
                                         SEQUENCE_LENGTH_MEAN,
                                         SEQUENCE_LENGTH_STDEV,
                                         sequence_name=name)
                    last_choices[client_idx] = "valid-valid"
                else:
                    sequence_valid(client_metadata,
                                   rng,
                                   trial,
                                   model_name,
                                   dtype,
                                   SEQUENCE_LENGTH_MEAN,
                                   SEQUENCE_LENGTH_STDEV,
                                   sequence_name=name)
                    last_choices[client_idx] = "valid"
            else:
                client_idx = 1
                client_metadata = client_metadata_list[client_idx]
                choice = rng.rand()

                if choice < 0.3:
                    timeout_client(client_metadata_list[client_idx], name)
                    last_choices[client_idx] = "timeout-client"
                elif choice < 0.5:
                    resnet_model_request(name)
                    last_choices[client_idx] = "resnet-request"
                else:
                    crashing_client(name)
                    last_choices[client_idx] = "crashing-client"

    except Exception as ex:
        _thread_exceptions_mutex.acquire()
        try:
            _thread_exceptions.append(traceback.format_exc())
        finally:
            _thread_exceptions_mutex.release()

    # We need to explicitly close each client so that streams get
    # cleaned up and closed correctly, otherwise the application
    # can hang when exiting.
    for c, i in client_metadata_list:
        print("thread {} closing client {}".format(name, i))
        c.close()

    print("Exiting thread {}".format(name))
    check_status(model_name)


def check_status(model_name):
    client = grpcclient.InferenceServerClient("localhost:8001",
                                              verbose=FLAGS.verbose)
    stats = client.get_inference_statistics(model_name)
    print(stats)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v',
                        '--verbose',
                        action="store_true",
                        required=False,
                        default=False,
                        help='Enable verbose output')
    parser.add_argument('-r',
                        '--random-seed',
                        type=int,
                        required=False,
                        help='Random seed.')
    parser.add_argument('-t',
                        '--concurrency',
                        type=int,
                        required=False,
                        default=8,
                        help='Request concurrency. Default is 8.')
    parser.add_argument(
        '-d',
        '--test-duration',
        type=int,
        required=False,
        default=160,
        help='Duration of stress test to run. Default is 160 seconds.')
    FLAGS = parser.parse_args()

    # Initialize the random seed. For reproducibility each thread
    # maintains its own RNG which is initialized based on this seed.
    randseed = 0
    if FLAGS.random_seed != None:
        randseed = FLAGS.random_seed
    else:
        randseed = int(time.time())
    np.random.seed(randseed)

    print("random seed = {}".format(randseed))
    print("concurrency = {}".format(FLAGS.concurrency))
    print("test duration = {}".format(FLAGS.test_duration))

    threads = []
    for idx, thd in enumerate(range(FLAGS.concurrency)):
        thread_name = "thread_{}".format(idx)

        # Create the seed for the thread. Since these are created in
        # reproducible order off of the initial seed we will get
        # reproducible results when given the same seed.
        seed = np.random.randint(2**32)

        # Each thread is reserved a block of correlation IDs or size
        # CORRELATION_ID_BLOCK_SIZE
        correlation_id_base = 1 + (idx * CORRELATION_ID_BLOCK_SIZE)

        threads.append(
            threading.Thread(target=stress_thread,
                             args=(thread_name, seed, FLAGS.test_duration,
                                   correlation_id_base)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _thread_exceptions_mutex.acquire()
    try:
        if len(_thread_exceptions) > 0:
            for ex in _thread_exceptions:
                print("*********\n{}".format(ex))
            sys.exit(1)
    finally:
        _thread_exceptions_mutex.release()

    print("Exiting stress test")
    sys.exit(0)
