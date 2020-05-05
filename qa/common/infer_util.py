# Copyright (c) 2018-2020, NVIDIA CORPORATION. All rights reserved.
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
import os
import numpy as np
import tritongrpcclient.core as grpcclient
import tritonhttpclient.core as httpclient
from tritonhttpclient.utils import *
import tritonsharedmemoryutils.shared_memory as shm
import tritonsharedmemoryutils.cuda_shared_memory as cudashm
import test_util as tu
import shm_util as su

# unicode() doesn't exist on python3, for how we use it the
# corresponding function is bytes()
if sys.version_info.major == 3:
    unicode = bytes

_seen_request_ids = set()


def _unique_request_id():
    if len(_seen_request_ids) == 0:
        return 1
    else:
        return max(_seen_request_ids) + 1


def _range_repr_dtype(dtype):
    if dtype == np.float64:
        return np.int32
    elif dtype == np.float32:
        return np.int16
    elif dtype == np.float16:
        return np.int8
    elif dtype == np.object:  # TYPE_STRING
        return np.int32
    return dtype


def _serialize_byte_tensor_list(tensor_values):
    tensor_list = []
    for tensor_value in tensor_values:
        tensor_list.append(serialize_byte_tensor(tensor_value))
    return tensor_list

# Perform inference using an "addsum" type verification backend.
def infer_exact(tester, pf, tensor_shape, batch_size,
                input_dtype, output0_dtype, output1_dtype,
                output0_raw=True, output1_raw=True,
                model_version=None, swap=False,
                outputs=("OUTPUT0", "OUTPUT1"), use_http=True, use_grpc=True,
                use_http_json_tensors=True, skip_request_id_check=False, use_streaming=True,
                correlation_id=0, shm_region_names=None, precreated_shm_regions=None,
                use_system_shared_memory=False, use_cuda_shared_memory=False,
                priority=0, timeout_us=0):
    tester.assertTrue(
        use_http or use_http_json_tensors or use_grpc or use_streaming)
    configs = []
    if use_http:
            configs.append(("localhost:8000", "http", False, True))
    if output0_raw == output1_raw:
        # Float16 not supported for Input and Output via JSON
        if use_http_json_tensors and (input_dtype != np.float16) and \
            (output0_dtype != np.float16) and (output1_dtype != np.float16):
            configs.append(("localhost:8000", "http", False, False))
    if use_grpc:
        configs.append(("localhost:8001", "grpc", False, False))
    if use_streaming:
        configs.append(("localhost:8001", "grpc", True, False))

    # outputs are sum and difference of inputs so set max input
    # values so that they will not overflow the output. This
    # allows us to do an exact match. For float types use 8, 16,
    # 32 int range for fp 16, 32, 64 respectively. When getting
    # class outputs the result value/probability is returned as a
    # float so must use fp32 range in that case.
    rinput_dtype = _range_repr_dtype(input_dtype)
    routput0_dtype = _range_repr_dtype(
        output0_dtype if output0_raw else np.float32)
    routput1_dtype = _range_repr_dtype(
        output1_dtype if output1_raw else np.float32)
    val_min = max(np.iinfo(rinput_dtype).min,
                  np.iinfo(routput0_dtype).min,
                  np.iinfo(routput1_dtype).min) / 2
    val_max = min(np.iinfo(rinput_dtype).max,
                  np.iinfo(routput0_dtype).max,
                  np.iinfo(routput1_dtype).max) / 2

    num_classes = 3

    input0_array = np.random.randint(low=val_min, high=val_max,
                                     size=tensor_shape, dtype=rinput_dtype)
    input1_array = np.random.randint(low=val_min, high=val_max,
                                     size=tensor_shape, dtype=rinput_dtype)
    if input_dtype != np.object:
        input0_array = input0_array.astype(input_dtype)
        input1_array = input1_array.astype(input_dtype)

    if not swap:
        output0_array = input0_array + input1_array
        output1_array = input0_array - input1_array
    else:
        output0_array = input0_array - input1_array
        output1_array = input0_array + input1_array

    if output0_dtype == np.object:
        output0_array = np.array([unicode(str(x), encoding='utf-8')
                                  for x in (output0_array.flatten())], dtype=object).reshape(output0_array.shape)
    else:
        output0_array = output0_array.astype(output0_dtype)
    if output1_dtype == np.object:
        output1_array = np.array([unicode(str(x), encoding='utf-8')
                                  for x in (output1_array.flatten())], dtype=object).reshape(output1_array.shape)
    else:
        output1_array = output1_array.astype(output1_dtype)

    if input_dtype == np.object:
        in0n = np.array([str(x)
                         for x in input0_array.reshape(input0_array.size)], dtype=object)
        input0_array = in0n.reshape(input0_array.shape)
        in1n = np.array([str(x)
                         for x in input1_array.reshape(input1_array.size)], dtype=object)
        input1_array = in1n.reshape(input1_array.shape)

    # prepend size of string to output string data
    if output0_dtype == np.object:
        if batch_size == 1:
            output0_array_tmp = _serialize_byte_tensor_list([output0_array])
        else:
            output0_array_tmp = _serialize_byte_tensor_list(output0_array)
    else:
        output0_array_tmp = output0_array

    if output1_dtype == np.object:
        if batch_size == 1:
            output1_array_tmp = _serialize_byte_tensor_list([output1_array])
        else:
            output1_array_tmp = _serialize_byte_tensor_list(output1_array)
    else:
        output1_array_tmp = output1_array

    OUTPUT0 = "OUTPUT0"
    OUTPUT1 = "OUTPUT1"
    INPUT0 = "INPUT0"
    INPUT1 = "INPUT1"
    if pf == "libtorch" or pf == "libtorch_nobatch":
        OUTPUT0 = "OUTPUT__0"
        OUTPUT1 = "OUTPUT__1"
        INPUT0 = "INPUT__0"
        INPUT1 = "INPUT__1"

    output0_byte_size = sum([o0.nbytes for o0 in output0_array_tmp])
    output1_byte_size = sum([o1.nbytes for o1 in output1_array_tmp])

    if batch_size == 1:
        input0_list = [input0_array]
        input1_list = [input1_array]
    else:
        input0_list = [x for x in input0_array]
        input1_list = [x for x in input1_array]

    # Serialization of string tensors in the case of shared memory must be done manually
    if input_dtype == np.object:
        input0_list_tmp = _serialize_byte_tensor_list(input0_list)
        input1_list_tmp = _serialize_byte_tensor_list(input1_list)
    else:
        input0_list_tmp = input0_list
        input1_list_tmp = input1_list

    input0_byte_size = sum([i0.nbytes for i0 in input0_list_tmp])
    input1_byte_size = sum([i1.nbytes for i1 in input1_list_tmp])

    # Create and register system/cuda shared memory regions if needed
    shm_regions, shm_handles = su.create_set_shm_regions(input0_list_tmp, input1_list_tmp, output0_byte_size,
                                                                    output1_byte_size, outputs, shm_region_names, precreated_shm_regions,
                                                                    use_system_shared_memory, use_cuda_shared_memory)

    # Run inference and check results for each config
    for config in configs:
        model_name = tu.get_model_name(
            pf, input_dtype, output0_dtype, output1_dtype)

        if config[1] == "http":
            triton_client = httpclient.InferenceServerClient(
                config[0], verbose=True)
        else:
            triton_client = grpcclient.InferenceServerClient(
                config[0], verbose=True)

        inputs = []
        if config[1] == "http":
            inputs.append(httpclient.InferInput(
                INPUT0, tensor_shape, np_to_triton_dtype(input_dtype)))
            inputs.append(httpclient.InferInput(
                INPUT1, tensor_shape, np_to_triton_dtype(input_dtype)))
        else:
            inputs.append(grpcclient.InferInput(
                INPUT0, tensor_shape, np_to_triton_dtype(input_dtype)))
            inputs.append(grpcclient.InferInput(
                INPUT1, tensor_shape, np_to_triton_dtype(input_dtype)))

        if not (use_cuda_shared_memory or use_system_shared_memory):
            if config[1] == "http":
                inputs[0].set_data_from_numpy(
                    input0_array, binary_data=config[3])
                inputs[1].set_data_from_numpy(
                    input1_array, binary_data=config[3])
            else:
                inputs[0].set_data_from_numpy(input0_array)
                inputs[1].set_data_from_numpy(input1_array)
        else:
            su.register_add_shm_regions(inputs, outputs, shm_regions, precreated_shm_regions, shm_handles,
                                input0_byte_size, input1_byte_size, output0_byte_size, output1_byte_size,
                                use_system_shared_memory, use_cuda_shared_memory, triton_client)

        if batch_size == 1:
            expected0_sort_idx = [np.flip(np.argsort(x.flatten()), 0)
                                  for x in output0_array.reshape((1,) + tensor_shape)]
            expected1_sort_idx = [np.flip(np.argsort(x.flatten()), 0)
                                  for x in output1_array.reshape((1,) + tensor_shape)]
        else:
            expected0_sort_idx = [np.flip(np.argsort(x.flatten()), 0)
                                  for x in output0_array.reshape(tensor_shape)]
            expected1_sort_idx = [np.flip(np.argsort(x.flatten()), 0)
                                  for x in output1_array.reshape(tensor_shape)]

        # Force binary_data = False for shared memory and class
        output_req = []
        i = 0
        if "OUTPUT0" in outputs:
            if len(shm_regions) != 0:
                if config[1] == "http":
                    output_req.append(httpclient.InferRequestedOutput(
                        OUTPUT0, binary_data=False))
                else:
                    output_req.append(grpcclient.InferRequestedOutput(OUTPUT0))

                if precreated_shm_regions is None:
                    output_req[-1].set_shared_memory(
                        shm_regions[2]+'_data', output0_byte_size)
                else:
                    output_req[-1].set_shared_memory(
                        precreated_shm_regions[0], output0_byte_size)
            else:
                if output0_raw:
                    if config[1] == "http":
                        output_req.append(httpclient.InferRequestedOutput(
                            OUTPUT0, binary_data=config[3]))
                    else:
                        output_req.append(
                            grpcclient.InferRequestedOutput(OUTPUT0))
                else:
                    if config[1] == "http":
                        output_req.append(httpclient.InferRequestedOutput(
                            OUTPUT0, binary_data=False, class_count=num_classes))
                    else:
                        output_req.append(grpcclient.InferRequestedOutput(
                            OUTPUT0, class_count=num_classes))
            i += 1
        if "OUTPUT1" in outputs:
            if len(shm_regions) != 0:
                if config[1] == "http":
                    output_req.append(httpclient.InferRequestedOutput(
                        OUTPUT1, binary_data=False))
                else:
                    output_req.append(grpcclient.InferRequestedOutput(OUTPUT1))

                if precreated_shm_regions is None:
                    output_req[-1].set_shared_memory(
                        shm_regions[2+i]+'_data', output1_byte_size)
                else:
                    output_req[-1].set_shared_memory(
                        precreated_shm_regions[i], output1_byte_size)
            else:
                if output1_raw:
                    if config[1] == "http":
                        output_req.append(httpclient.InferRequestedOutput(
                            OUTPUT1, binary_data=config[3]))
                    else:
                        output_req.append(
                            grpcclient.InferRequestedOutput(OUTPUT1))
                else:
                    if config[1] == "http":
                        output_req.append(httpclient.InferRequestedOutput(
                            OUTPUT1, binary_data=False, class_count=num_classes))
                    else:
                        output_req.append(grpcclient.InferRequestedOutput(
                            OUTPUT1, class_count=num_classes))

        if model_version is not None:
            model_version = str(model_version)
        else:
            model_version = ""

        if config[2]:
            # TODO fix for streaming case
            continue
            # results = triton_client.async_stream_infer(model_name,
            #                                  inputs,
            #                                  model_version=model_version,
            #                                  stream=stream,
            #                                  outputs=output_req)
        else:
            results = triton_client.infer(model_name,
                                          inputs,
                                          model_version=model_version,
                                          outputs=output_req,
                                          request_id=str(_unique_request_id()))

        last_response = results.get_response()
        if config[1] == "http":
            if 'error' in last_response:
                raise InferenceServerException(msg=last_response['error'])

        if not skip_request_id_check:
            global _seen_request_ids
            if config[1] == "http":
                request_id = int(last_response["id"])
            else:
                request_id = int(last_response.id)
            tester.assertFalse(request_id in _seen_request_ids,
                               "request_id: {}".format(request_id))
            _seen_request_ids.add(request_id)

        if config[1] == "http":
            response_model_name = last_response["model_name"]
        else:
            response_model_name = last_response.model_name
        tester.assertEqual(response_model_name, model_name)

        if model_version != "":
            if config[1] == "http":
                response_model_version = last_response["model_version"]
            else:
                response_model_version = last_response.model_version
            tester.assertEqual(response_model_version, model_version)

        if config[1] == "http":
            response_outputs = last_response["outputs"]
        else:
            response_outputs = last_response.outputs
        tester.assertEqual(len(response_outputs), len(outputs))

        for result in response_outputs:
            if config[1] == "http":
                result_name = result["name"]
            else:
                result_name = result.name

            if ((result_name == OUTPUT0 and output0_raw) or
                    (result_name == OUTPUT1 and output1_raw)):
                if use_system_shared_memory or use_cuda_shared_memory:
                    if result_name == OUTPUT0:
                        shm_handle = shm_handles[2]
                    else:
                        shm_handle = shm_handles[3]

                    output = results.get_output(result_name)
                    if config[1] == "http":
                        output_datatype = output['datatype']
                        output_shape = output['shape']
                    else:
                        output_datatype = output.datatype
                        output_shape = output.shape
                    output_dtype = triton_to_np_dtype(output_datatype)
                if use_system_shared_memory:
                    output_data = shm.get_contents_as_numpy(
                        shm_handle, output_dtype, output_shape)
                elif use_cuda_shared_memory:
                    output_data = cudashm.get_contents_as_numpy(
                        shm_handle, output_dtype, output_shape)
                else:
                    output_data = results.as_numpy(result_name)

                if (output_data.dtype == np.object) and (config[3] == False):
                    output_data = output_data.astype(np.bytes_)

                if result_name == OUTPUT0:
                    tester.assertTrue(np.array_equal(output_data, output0_array),
                                      "{}, {} expected: {}, got {}".format(
                        model_name, OUTPUT0, output0_array, output_data))
                elif result_name == OUTPUT1:
                    tester.assertTrue(np.array_equal(output_data, output1_array),
                                      "{}, {} expected: {}, got {}".format(
                        model_name, OUTPUT1, output1_array, output_data))
                else:
                    tester.assertTrue(
                        False, "unexpected raw result {}".format(result_name))
            else:
                for b in range(batch_size):
                    # num_classes values must be returned and must
                    # match expected top values
                    class_list = results.as_numpy(result_name)[b]
                    tester.assertEqual(len(class_list), num_classes)
                    if batch_size == 1:
                        expected0_flatten = output0_array.flatten()
                        expected1_flatten = output1_array.flatten()
                    else:
                        expected0_flatten = output0_array[b].flatten()
                        expected1_flatten = output1_array[b].flatten()

                    for idx, class_label in enumerate(class_list):
                        # can't compare indices since could have different
                        # indices with the same value/prob, so check that
                        # the value of each index equals the expected value.
                        # Only compare labels when the indices are equal.
                        if type(class_label) == str:
                            ctuple = class_label.split(':')
                        else:
                            ctuple = "".join(chr(x)
                                         for x in class_label).split(':')
                        cidx = int(ctuple[0])
                        cval = float(ctuple[1])
                        if result_name == OUTPUT0:
                            tester.assertEqual(cval, expected0_flatten[cidx])
                            tester.assertEqual(
                                cval, expected0_flatten[expected0_sort_idx[b][idx]])
                            if cidx == expected0_sort_idx[b][idx]:
                                tester.assertEqual(ctuple[2], 'label{}'.format(
                                    expected0_sort_idx[b][idx]))
                        elif result_name == OUTPUT1:
                            tester.assertEqual(cval, expected1_flatten[cidx])
                            tester.assertEqual(
                                cval, expected1_flatten[expected1_sort_idx[b][idx]])
                        else:
                            tester.assertTrue(
                                False, "unexpected class result {}".format(result_name))

    # Unregister system/cuda shared memory regions if they exist
    su.unregister_cleanup_shm_regions(shm_regions, shm_handles, precreated_shm_regions, outputs,
                                      use_system_shared_memory, use_cuda_shared_memory)

    return results

# Perform inference on a model that takes a shape and a dummy tensors as inputs,
# resize the dummy tensor with the provided values in the shape tensor and finally
# return the shape of the resized tensor.
def infer_shape_tensor(tester, pf, tensor_dtype, input_shape_values, dummy_input_shapes,
               use_http=True, use_grpc=True,
               use_streaming=True, shm_suffix="", use_system_shared_memory=False,
               use_cuda_shared_memory=False, priority=0, timeout_us=0,
               batch_size=1):
    tester.assertTrue(use_http or use_grpc or use_streaming)
    tester.assertTrue(pf == "plan" or pf == "plan_nobatch")
    tester.assertEqual(len(input_shape_values), len(dummy_input_shapes))
    if use_system_shared_memory and use_cuda_shared_memory:
        raise ValueError("Cannot set both System and CUDA shared memory flags to 1")

    configs = []
    if use_http:
        configs.append(("localhost:8000", "http", False))
    if use_grpc:
        configs.append(("localhost:8001", "grpc", False))
    if use_streaming:
        configs.append(("localhost:8001", "grpc", True))

    io_cnt = len(input_shape_values)

    # FIXME wrap up shm handle cleanup
    # For (cuda) shared memory, it's only set for shape tensor for simplicity.
    # Regular tensor with (cuda) shared memory should be well-tested in other
    # tests.
    # item is (handle, byte_size, is_cuda)
    input_shm_handle_list = []
    output_shm_handle_list= []
    dummy_input_list = []
    input_list = []
    expected_dict = dict()
    # Prepare IO in advance
    for io_num in range(io_cnt):
        dummy_input_name = "DUMMY_INPUT{}".format(io_num)
        input_name = "INPUT{}".format(io_num)
        dummy_output_name = "DUMMY_OUTPUT{}".format(io_num)
        output_name = "OUTPUT{}".format(io_num)

        # Prepare the dummy tensor
        rtensor_dtype = _range_repr_dtype(tensor_dtype)
        if (rtensor_dtype != np.bool):
            dummy_in0 = np.random.randint(low=np.iinfo(rtensor_dtype).min,
                                    high=np.iinfo(rtensor_dtype).max,
                                    size=dummy_input_shapes[io_num], dtype=rtensor_dtype)
        else:
            dummy_in0 = np.random.choice(a=[False, True], size=dummy_input_shapes[io_num])
        if tensor_dtype != np.object:
            dummy_in0 = dummy_in0.astype(tensor_dtype)
        else:
            dummy_in0 = np.array([str(x) for x in dummy_in0.flatten()],
                            dtype=object).reshape(dummy_in0.shape)
        dummy_input_list.append(dummy_in0)

        # Prepare shape input tensor
        in0 = np.asarray(input_shape_values[io_num], dtype=np.int32)
        input_list.append(in0)

        # Prepare the expected value for the output. Skip dummy output as we
        # only care about its shape (== value of OUTPUT*)
        expected_dict[output_name] = np.ndarray.copy(in0)

        # Only need to create region once
        input_byte_size = in0.size * np.dtype(np.int32).itemsize
        output_byte_size = input_byte_size * batch_size
        if use_system_shared_memory:
            input_shm_handle_list.append((shm.create_shared_memory_region(input_name+shm_suffix,
                                                            '/'+input_name+shm_suffix, input_byte_size), input_byte_size, False))
            output_shm_handle_list.append((shm.create_shared_memory_region(output_name+shm_suffix,
                                                            '/'+output_name+shm_suffix, output_byte_size), output_byte_size, False))
            shm.set_shared_memory_region(input_shm_handle_list[-1][0], [in0,])
        elif use_cuda_shared_memory:
            input_shm_handle_list.append((cudashm.create_shared_memory_region(input_name+shm_suffix,
                                                            input_byte_size, 0), input_byte_size, True))
            output_shm_handle_list.append((cudashm.create_shared_memory_region(output_name+shm_suffix,
                                                            output_byte_size, 0), output_byte_size, True))
            cudashm.set_shared_memory_region(input_shm_handle_list[-1][0], [in0,])

    model_name = tu.get_zero_model_name(pf, io_cnt, tensor_dtype)
    # Run inference and check results for each config
    for config in configs:
        client_utils = grpcclient if config[1] == "grpc" else httpclient
        triton_client = client_utils.InferenceServerClient(config[0], verbose=True)

        inputs = []
        outputs = []

        # Set IOs
        for io_num in range(io_cnt):
            dummy_input_name = "DUMMY_INPUT{}".format(io_num)
            input_name = "INPUT{}".format(io_num)
            dummy_output_name = "DUMMY_OUTPUT{}".format(io_num)
            output_name = "OUTPUT{}".format(io_num)

            inputs.append(client_utils.InferInput(
                dummy_input_name, dummy_input_shapes[io_num],
                np_to_triton_dtype(tensor_dtype)))
            inputs.append(client_utils.InferInput(
                input_name, input_list[io_num].shape, "INT32"))
            outputs.append(client_utils.InferRequestedOutput(
                dummy_output_name))
            outputs.append(client_utils.InferRequestedOutput(
                output_name))

            # -2: dummy; -1: input
            inputs[-2].set_data_from_numpy(dummy_input_list[io_num])
            if (not use_system_shared_memory) and (not use_cuda_shared_memory):
                inputs[-1].set_data_from_numpy(input_list[io_num])
            else:
                input_byte_size = input_shm_handle_list[io_num][1]
                output_byte_size = output_shm_handle_list[io_num][1]
                if use_system_shared_memory:
                    triton_client.register_system_shared_memory(input_name+shm_suffix, "/"+input_name+shm_suffix, input_byte_size)
                    triton_client.register_system_shared_memory(output_name+shm_suffix, "/"+output_name+shm_suffix, output_byte_size)
                else:
                    triton_client.register_cuda_shared_memory(input_name+shm_suffix, cudashm.get_raw_handle(input_shm_handle_list[io_num][0]), 0, input_byte_size)
                    triton_client.register_cuda_shared_memory(output_name+shm_suffix, cudashm.get_raw_handle(output_shm_handle_list[io_num][0]), 0, output_byte_size)
                inputs[-1].set_shared_memory(input_name+shm_suffix, input_byte_size)
                outputs[-1].set_shared_memory(output_name+shm_suffix, output_byte_size)
            
        # FIXME streaming needs async handling
        results = triton_client.infer(model_name, inputs,
                                      outputs=outputs,
                                      priority=priority, timeout=timeout_us)

        for io_num in range(io_cnt):
            output_name = "OUTPUT{}".format(io_num)
            dummy_output_name = "DUMMY_OUTPUT{}".format(io_num)
            expected = expected_dict[output_name]

            # get outputs as numpy array
            dummy_out = results.as_numpy(dummy_output_name)
            if (not use_system_shared_memory) and (not use_cuda_shared_memory):
                out = results.as_numpy(output_name)
            else:
                output = results.get_output(output_name)
                if config[1] == "grpc":
                    output_shape = output.shape
                else:
                    output_shape = output["shape"]
                if use_system_shared_memory:
                    out = shm.get_contents_as_numpy(output_shm_handle_list[io_num][0], np.int32, output_shape)
                else:
                    out = cudashm.get_contents_as_numpy(output_shm_handle_list[io_num][0], np.int32, output_shape)

            # if out shape is 2D, it is batched
            if (len(out.shape) == 2):
                # The shape of the dummy output should be equal to the shape values
                # specified in the shape tensor
                tester.assertTrue(np.array_equal(dummy_out.shape[1:], out[0]),
                                  "{}, {} shape, expected: {}, got {}".format(
                                      model_name, dummy_output_name, out[0], dummy_out.shape[1:]))
                for b in range(1, out.shape[0]):
                    tester.assertTrue(np.array_equal(out[b-1], out[b]),
                                      "expect shape tensor has consistent value, "
                                      "expected: {}, got {}".format(out[b-1], out[b]))
                out = out[0]
            else:
                tester.assertTrue(np.array_equal(dummy_out.shape, out),
                                  "{}, {} shape, expected: {}, got {}".format(
                                      model_name, dummy_output_name, out, dummy_out.shape))
            tester.assertTrue(np.array_equal(out, expected),
                              "{}, {}, expected: {}, got {}".format(
                              model_name, output_name, expected, out))

            # unregister shared memory region for next config
            if use_system_shared_memory:
                triton_client.unregister_system_shared_memory(input_name+shm_suffix)
                triton_client.unregister_system_shared_memory(output_name+shm_suffix)
            elif use_cuda_shared_memory:
                triton_client.unregister_cuda_shared_memory(input_name+shm_suffix)
                triton_client.unregister_cuda_shared_memory(output_name+shm_suffix)

    for handle in input_shm_handle_list:
        if (handle[2]):
            cudashm.destroy_shared_memory_region(handle[0])
        else:
            shm.destroy_shared_memory_region(handle[0])
    for handle in output_shm_handle_list:
        if (handle[2]):
            cudashm.destroy_shared_memory_region(handle[0])
        else:
            shm.destroy_shared_memory_region(handle[0])
