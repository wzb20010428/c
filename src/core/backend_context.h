// Copyright (c) 2019-2020, NVIDIA CORPORATION. All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions
// are met:
//  * Redistributions of source code must retain the above copyright
//    notice, this list of conditions and the following disclaimer.
//  * Redistributions in binary form must reproduce the above copyright
//    notice, this list of conditions and the following disclaimer in the
//    documentation and/or other materials provided with the distribution.
//  * Neither the name of NVIDIA CORPORATION nor the names of its
//    contributors may be used to endorse or promote products derived
//    from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
// EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
// PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
// CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
// EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
// PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
// PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
// OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#pragma once

#include <list>
#include <memory>
#include <string>
#include <vector>
#include "src/core/infer_request.h"
#include "src/core/memory.h"
#include "src/core/model_config.h"
#include "src/core/status.h"

#ifdef TRTIS_ENABLE_GPU
#include <cuda_runtime_api.h>
#endif  // TRTIS_ENABLE_GPU

namespace nvidia { namespace inferenceserver {

class InferenceBackend;
class InferenceRequest;

struct InputInfo {
  char* input_buffer_;
  TRITONSERVER_MemoryType memory_type_;
  int64_t memory_type_id_;
  // indirect pinned memory buffers, their locations in 'input_buffer_',
  // and the requests that are associated with this buffer (for reporting error)
  std::vector<
      std::tuple<std::unique_ptr<AllocatedMemory>, size_t, std::vector<size_t>>>
      indirect_buffers_;
};

struct BackendContext {
 public:
#ifndef TRTIS_ENABLE_GPU
  using cudaStream_t = void*;
#endif  // !TRTIS_ENABLE_GPU

  // GPU device number that indicates that no gpu is available for a
  // context (which is an invalid state since TensorRT requires a
  // GPU).
  static constexpr int NO_GPU_DEVICE = -1;

  // Max batch size value that indicates batching is not supported.
  static constexpr int NO_BATCHING = 0;

  BackendContext(
      const std::string& name, const int gpu_device, const int max_batch_size,
      const bool enable_pinned_input, const bool enable_pinned_output);

  virtual ~BackendContext();

  // Create the CUDA stream for data transfer operations. If 'stream' is
  // nullptr, the stream will be created on 'stream_'. Have no effect if GPU
  // support is disabled.
  Status CreateCudaStream(
      const int cuda_stream_priority = 0, cudaStream_t* stream = nullptr);

  // Run model to execute one or more requests. This function assumes
  // that it is only called by the single runner thread that is
  // assigned to this context. This function takes ownership of
  // 'requests' and is responsible for generating responses and
  // releasing the requests.
  virtual void Run(
      const InferenceBackend* base,
      std::vector<std::unique_ptr<InferenceRequest>>&& requests) = 0;

  // Return the contents of a shape tensor. It is the caller's
  // responsibility to call this only for shape tensors that are
  // 1-dimensional, INT32 tensors. A non-OK status indicates that the
  // contents of the tensor could not be peeked.
  virtual Status PeekShapeTensor(
      const InferenceRequest::Input& input,
      const std::unique_ptr<InferenceRequest>& request,
      std::vector<int64_t>* shape);

  // Helper function to batch input data from requests into
  // 'input_buffer'.  'input_buffer' must be a continuous block that
  // can hold the sum of 'expected_byte_sizes' bytes. On byte size
  // mismatch, the function will send an appropriate error response
  // for the request.  Return true if cudaMemcpyAsync is called, and
  // the caller should call cudaStreamSynchronize before using the
  // data. Otherwise, return false.
  bool SetInputBuffer(
      const std::string& name, const std::vector<size_t>& expected_byte_sizes,
      std::vector<std::unique_ptr<InferenceRequest>>* requests,
      InputInfo* input);

  // Overload of SetInputBuffer() which issues the CUDA copies on 'stream'
  // instead of 'stream_'.
  bool SetInputBuffer(
      const std::string& name, const std::vector<size_t>& expected_byte_sizes,
      std::vector<std::unique_ptr<InferenceRequest>>* requests,
      cudaStream_t stream, InputInfo* input);

  // Helper function to populate the shape value of specified shape input
  // that corresponds with the batch size. The first shape value is asssumed
  // to be the batch size. Its the user's responsibility to ensure it is called
  // only for the shape tensors.
  // Return true if cudaMemcpyAsync is called, and the caller should call
  // cudaStreamSynchronize before using the data. Otherwise, return false.
  bool SetShapeInputBuffer(
      const std::string& name, const int32_t total_batch_size,
      const int expected_byte_size, const bool support_batching,
      std::unique_ptr<InferenceRequest>& request,
      TRITONSERVER_MemoryType dst_memory_type, int64_t dst_memory_type_id,
      char* input_buffer);

  // Helper function to set output buffer for a shape tensor. It is
  // callers resposibilty to ensure this method is called only for the
  // shape tensors. Return true if cudaMemcpyAsync is called, and the
  // caller should call cudaStreamSynchronize before using the
  // data. Otherwise, return false.
  bool SetOutputShapeTensorBuffer(
      const std::string& name, const int32_t* content,
      std::vector<int64_t>& content_shape, const bool support_batching,
      TRITONSERVER_MemoryType src_memory_type, int64_t src_memory_type_id,
      std::vector<std::unique_ptr<InferenceRequest>>* requests);

  // This function will return a tensor's contents as a contiguous
  // chunk. In some cases this will require copying the data. If that
  // happens, 'contiguous_buffer' will be set to hold the contiguous
  // chunk and 'cuda_copy' will be set to indicate whether CUDA copy
  // is conducted.  The data copy can be avoided if the input is
  // already in a contiguous chunk and the input is located in memory
  // type and id specified.
  Status GetContiguousInputContent(
      const std::string& name, TRITONSERVER_MemoryType memory_type,
      int64_t memory_type_id, const std::unique_ptr<InferenceRequest>& request,
      const char** content, size_t* content_byte_size,
      std::unique_ptr<AllocatedMemory>* contiguous_buffer, bool* cuda_copy);

  // Check if output tensor produced by a model is compatible with the
  // model configuration.  Dimensions with variable size in the model
  // configuration can support any size in the corresponding output
  // tensor dimension.
  //
  // \param supports_batching If True then the configuration expects
  // the model to support batching and so the shape must have the
  // appropriate batch dimension.
  Status CompareOutputDims(
      const std::string& tensor_name, const std::vector<int64_t>& model_shape,
      const DimsList& dims, const bool supports_batching);

  // Meta data for constructing an indirect pinned memory buffer for input
  // <offset in input buffer,
  //  indirect buffer size,
  //  vector of <index of the request (for status update),
  //             memory block of the provider's input,
  //             index in the memory block>>
  using BufferInfo = std::tuple<
      size_t, size_t, std::vector<std::tuple<size_t, const Memory*, size_t>>>;

  // Helper function to construct an 'indirect_buffer', and to copy
  // data in 'requests' to the indirect buffer first, then to copy the
  // indirect buffer to proper location in 'input_buffer', according
  // to 'pinned_buffer_info'.
  bool IssueIndirectInputBufferCopy(
      const std::string& name, const BufferInfo& pinned_buffer_info,
      std::vector<std::unique_ptr<InferenceRequest>>* requests,
      cudaStream_t stream, InputInfo* input);

  // Name of the model instance
  std::string name_;

  // The GPU index active when this context was created.
  const int gpu_device_;

  // Maximum batch size to allow. This is the minimum of what is
  // supported by the model and what is requested in the
  // configuration.
  const int max_batch_size_;

  // Whether to use indirect pinned buffer for the corresponding data copy type.
  const bool enable_pinned_input_;
  const bool enable_pinned_output_;

  // The stream where data transfer operations are executed on.
  cudaStream_t stream_;
};

class BackendResponder {
 public:
  explicit BackendResponder(
      const std::vector<std::unique_ptr<InferenceRequest>>& requests,
      std::vector<std::unique_ptr<InferenceResponse>>* responses,
      const bool pinned_enabled, cudaStream_t stream)
      : need_sync_(false), requests_(requests), responses_(responses),
        pinned_enabled_(pinned_enabled), stream_(stream),
        pending_pinned_byte_size_(0)
  {
  }

  // Process all responses for a named output tensor.
  void ProcessTensor(
      const std::string& name, const DataType datatype,
      const std::vector<int64_t>& shape, const char* buffer,
      const TRITONSERVER_MemoryType memory_type, const int64_t memory_type_id);

  // Finalize processing of all responses for all output
  // tensors. Return true if cudaMemcpyAsync is called, and the caller
  // should call cudaStreamSynchronize before using the data.
  bool Finalize();

 private:
  bool FlushPendingPinned(
      const char* tensor_buffer,
      const TRITONSERVER_MemoryType tensor_memory_type,
      const int64_t tensor_memory_type_id);
  bool SetFixedSizeOutputBuffer(
      std::unique_ptr<InferenceResponse>* response,
      InferenceResponse::Output* response_output, const size_t tensor_byte_size,
      const size_t tensor_offset, const char* tensor_buffer,
      const TRITONSERVER_MemoryType tensor_memory_type,
      const int64_t tensor_memory_type_id,
      const TRITONSERVER_MemoryType use_pinned_memory_type);

  bool need_sync_;
  const std::vector<std::unique_ptr<InferenceRequest>>& requests_;
  std::vector<std::unique_ptr<InferenceResponse>>* responses_;
  const bool pinned_enabled_;
  cudaStream_t stream_;

  using ResponsesList = std::list<std::pair<
      std::unique_ptr<InferenceResponse>*, InferenceResponse::Output*>>;

  size_t pending_pinned_byte_size_;
  size_t pending_pinned_offset_;
  ResponsesList pending_pinned_output_;

  // Pinned memories that need to live over the lifetime of this
  // BackendResponder object.
  std::list<std::unique_ptr<AllocatedMemory>> pinned_memories_;

  // Pinned memory buffers and the corresponding response outputs
  // where the final copy to the response is deferred until Finalize()
  // after waiting for all in-flight copies.
  struct DeferredPinned {
    DeferredPinned(
        std::unique_ptr<AllocatedMemory>&& pinned_memory,
        ResponsesList&& responses)
        : pinned_memory_(std::move(pinned_memory)),
          responses_(std::move(responses))
    {
    }
    std::unique_ptr<AllocatedMemory> pinned_memory_;
    ResponsesList responses_;
  };

  std::list<DeferredPinned> deferred_pinned_;
};

}}  // namespace nvidia::inferenceserver
