import argparse
import concurrent.futures as futures
import importlib.util
import sys
import threading

import numpy as np

from python_host_pb2 import *
from python_host_pb2_grpc import PythonInterpreterServicer, add_PythonInterpreterServicer_to_server
import grpc

_TYPE_MAPPING_DICTIONARY = {
    # TRITONSERVER_TYPE_BOOL
    1: np.bool,
    # TRITONSERVER_TYPE_UINT8
    2: np.uint8,
    # TRITONSERVER_TYPE_UINT16
    3: np.uint16,
    # TRITONSERVER_TYPE_UINT32
    4: np.uint32,
    # TRITONSERVER_TYPE_UINT64
    5: np.uint64,
    # TRITONSERVER_TYPE_INT8
    6: np.int8,
    # TRITONSERVER_TYPE_INT16
    7: np.int16,
    # TRITONSERVER_TYPE_INT32
    8: np.int32,
    # TRITONSERVER_TYPE_INT64
    9: np.int64,
    # TRITONSERVER_TYPE_FP16
    10: np.float16,
    # TRITONSERVER_TYPE_FP32
    11: np.float32,
    # TRITONSERVER_TYPE_FP64
    12: np.float64,
    # TRITONSERVER_TYPE_BYTES
    13: np.bytes_
}


def protobuf_to_numpy_type(data_type):
    return _TYPE_MAPPING_DICTIONARY[data_type]


def numpy_to_protobuf_type(data_type):
    return {v: k for k, v in _TYPE_MAPPING_DICTIONARY.items()}[data_type]


def parse_startup_arguments():
    parser = argparse.ArgumentParser(description="Triton Python Host")
    parser.add_argument("--socket",
                        default=None,
                        required=True,
                        type=str,
                        help="Socket to comunicate with server")
    parser.add_argument("--model_path",
                        default=None,
                        required=True,
                        type=str,
                        help="Path to model code")
    parser.add_argument("--instance_name",
                        default=None,
                        required=True,
                        type=str,
                        help="Triton instance name")
    return parser.parse_args()


lock = threading.Lock()
cv = threading.Condition(lock)


class PythonHost(PythonInterpreterServicer):
    r"""
    This class handles inference request for python script.
    """

    def __init__(self, module_path, *args, **kwargs):
        super(PythonInterpreterServicer, self).__init__(*args, **kwargs)
        spec = importlib.util.spec_from_file_location("triton", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "initialize_model"):
            self.initializer_func = module.initialize_model
        elif hasattr(module, "triton"):
            self.initializer_func = module.triton
        else:
            self.initializer_func = None
        self.model = None

    def Init(self, request, context):
        # if self.model:
        #     return StatusCode(code=0)

        # if not self.initializer_func:
        #     return StatusCode(code=1)
        args = {x.key: x.value for x in request.model_command}
        self.model = self.initializer_func(args)

        # if not self.model:
        #     return StatusCode(code=2)

        # return StatusCode(code=0)

    def Fini(self, request, context):
        if hasattr(self.model, "shutdown"):
            self.model.shutdown()

        del self.model
        with cv:
            cv.notify()
        # return StatusCode(code=0)

    def Execute(self, request, context):

        requests = request.requests
        np_requests = []
        for request in requests:
            request_inputs = {}
            for request_input in request.inputs:
                x = request_input
                request_inputs[x.name] = np.frombuffer(
                    x.raw_data,
                    dtype=protobuf_to_numpy_type(x.dtype)).reshape(x.dims)
            np_requests.append({
                'inputs': request_inputs,
                'id': request.id,
                'correlation_id': request.correlation_id,
                'requested_output_names': request.requested_output_names
            })
        responses = self.model(np_requests)
        exec_responses = []
        for response in responses:
            tensors = []
            for response_name, response_value in response.items():
                name = response_name
                tensor = Tensor(name=name,
                                dtype=numpy_to_protobuf_type(
                                    response_value.dtype.type),
                                dims=response_value.shape,
                                raw_data=response_value.tobytes())
                tensors.append(tensor)
            exec_responses.append(InferenceResponse(inputs=tensors))
        execute_response = ExecuteResponse(responses=exec_responses)

        return execute_response


if __name__ == "__main__":
    FLAGS = parse_startup_arguments()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    add_PythonInterpreterServicer_to_server(
        PythonHost(module_path=FLAGS.model_path), server)

    server.add_insecure_port(FLAGS.socket)
    server.start()

    with cv:
        cv.wait()
    server.stop(grace=5)
