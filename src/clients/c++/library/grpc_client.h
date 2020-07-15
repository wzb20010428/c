// Copyright (c) 2020, NVIDIA CORPORATION. All rights reserved.
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

/// \file

#include <queue>
#include "src/clients/c++/library/common.h"
#include "src/clients/c++/library/ipc.h"
#include "src/core/constants.h"
#include "src/core/grpc_service.grpc.pb.h"
#include "src/core/model_config.pb.h"

namespace nvidia { namespace inferenceserver { namespace client {

/// The key-value map type to be included in the request
/// metadata
typedef std::map<std::string, std::string> Headers;

struct SslOptions {
  explicit SslOptions() {}
  // File holding PEM-encoded root certificates
  std::string root_certificates;
  // File holding PEM-encoded private key
  std::string private_key;
  // File holding PEM-encoded certificate chain
  std::string certificate_chain;
};

//==============================================================================
/// An InferenceServerGrpcClient object is used to perform any kind of
/// communication with the InferenceServer using gRPC protocol.
///
/// \code
///   std::unique_ptr<InferenceServerGrpcClient> client;
///   InferenceServerGrpcClient::Create(&client, "localhost:8001");
///   bool live;
///   client->IsServerLive(&live);
///   ...
///   ...
/// \endcode
///
class InferenceServerGrpcClient : public InferenceServerClient {
 public:
  ~InferenceServerGrpcClient();

  /// Create a client that can be used to communicate with the server.
  /// \param client Returns a new InferenceServerGrpcClient object.
  /// \param server_url The inference server name and port.
  /// \param verbose If true generate verbose output when contacting
  /// the inference server.
  /// \param use_ssl If true use encrypted channel to the server.
  /// \param ssl_options Specifies the files required for
  /// SSL encryption and authorization.
  /// \return Error object indicating success or failure.
  static Error Create(
      std::unique_ptr<InferenceServerGrpcClient>* client,
      const std::string& server_url, bool verbose = false, bool use_ssl = false,
      const SslOptions& ssl_options = SslOptions());

  /// Contact the inference server and get its liveness.
  /// \param live Returns whether the server is live or not.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsServerLive(bool* live, const Headers& headers = Headers());

  /// Contact the inference server and get its readiness.
  /// \param ready Returns whether the server is ready or not.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsServerReady(bool* ready, const Headers& headers = Headers());

  /// Contact the inference server and get the readiness of specified model.
  /// \param ready Returns whether the specified model is ready or not.
  /// \param model_name The name of the model to check for readiness.
  /// \param model_version The version of the model to check for readiness.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error IsModelReady(
      bool* ready, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get its metadata.
  /// \param server_metadata Returns the server metadata as
  /// SeverMetadataResponse message.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error ServerMetadata(
      ServerMetadataResponse* server_metadata,
      const Headers& headers = Headers());

  /// Contact the inference server and get the metadata of specified model.
  /// \param model_metadata Returns model metadata as ModelMetadataResponse
  /// message.
  /// \param model_name The name of the model to get metadata.
  /// \param model_version The version of the model to get metadata.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error ModelMetadata(
      ModelMetadataResponse* model_metadata, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get the configuration of specified model.
  /// \param model_config Returns model config as ModelConfigResponse
  /// message.
  /// \param model_name The name of the model to get configuration.
  /// \param model_version The version of the model to get configuration.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error ModelConfig(
      ModelConfigResponse* model_config, const std::string& model_name,
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get the index of model repository
  /// contents.
  /// \param repository_index Returns the repository index as
  /// RepositoryIndexRequestResponse
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error ModelRepositoryIndex(
      RepositoryIndexResponse* repository_index,
      const Headers& headers = Headers());

  /// Request the inference server to load or reload specified model.
  /// \param model_name The name of the model to be loaded or reloaded.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error LoadModel(
      const std::string& model_name, const Headers& headers = Headers());

  /// Request the inference server to unload specified model.
  /// \param model_name The name of the model to be unloaded.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error UnloadModel(
      const std::string& model_name, const Headers& headers = Headers());

  /// Contact the inference server and get the inference statistics for the
  /// specified model name and version.
  /// \param infer_stat The inference statistics of requested model name and
  /// version.
  /// \param model_name The name of the model to get inference statistics. The
  /// default value is an empty string which means statistics of all models will
  /// be returned in the response.
  /// \param model_version The version of the model to get inference statistics.
  /// The default value is an empty string which means then the server will
  /// choose a version based on the model and internal policy.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error ModelInferenceStatistics(
      ModelStatisticsResponse* infer_stat, const std::string& model_name = "",
      const std::string& model_version = "",
      const Headers& headers = Headers());

  /// Contact the inference server and get the status for requested system
  /// shared memory.
  /// \param status The system shared memory status as
  /// SystemSharedMemoryStatusResponse
  /// \param region_name The name of the region to query status. The default
  /// value is an empty string, which means that the status of all active system
  /// shared memory will be returned.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error SystemSharedMemoryStatus(
      SystemSharedMemoryStatusResponse* status,
      const std::string& region_name = "", const Headers& headers = Headers());

  /// Request the server to register a system shared memory with the provided
  /// details.
  /// \param name The name of the region to register.
  /// \param key The key of the underlying memory object that contains the
  /// system shared memory region.
  /// \param byte_size The size of the system shared memory region, in bytes.
  /// \param offset Offset, in bytes, within the underlying memory object to
  /// the start of the system shared memory region. The default value is zero.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request
  Error RegisterSystemSharedMemory(
      const std::string& name, const std::string& key, const size_t byte_size,
      const size_t offset = 0, const Headers& headers = Headers());

  /// Request the server to unregister a system shared memory with the
  /// specified name.
  /// \param name The name of the region to unregister. The default value is
  /// empty string which means all the system shared memory regions will be
  /// unregistered.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request
  Error UnregisterSystemSharedMemory(
      const std::string& name = "", const Headers& headers = Headers());

  /// Contact the inference server and get the status for requested CUDA
  /// shared memory.
  /// \param status The CUDA shared memory status as
  /// CudaSharedMemoryStatusResponse
  /// \param region_name The name of the region to query status. The default
  /// value is an empty string, which means that the status of all active CUDA
  /// shared memory will be returned.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error CudaSharedMemoryStatus(
      CudaSharedMemoryStatusResponse* status,
      const std::string& region_name = "", const Headers& headers = Headers());

  /// Request the server to register a CUDA shared memory with the provided
  /// details.
  /// \param name The name of the region to register.
  /// \param cuda_shm_handle The cudaIPC handle for the memory object.
  /// \param device_id The GPU device ID on which the cudaIPC handle was
  /// created.
  /// \param byte_size The size of the CUDA shared memory region, in
  /// bytes.
  /// \param headers Optional map specifying additional HTTP headers to
  /// include in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request
  Error RegisterCudaSharedMemory(
      const std::string& name, const cudaIpcMemHandle_t& cuda_shm_handle,
      const size_t device_id, const size_t byte_size,
      const Headers& headers = Headers());

  /// Request the server to unregister a CUDA shared memory with the
  /// specified name.
  /// \param name The name of the region to unregister. The default value is
  /// empty string which means all the CUDA shared memory regions will be
  /// unregistered.
  /// \param headers Optional map specifying additional HTTP headers to
  /// include in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request
  Error UnregisterCudaSharedMemory(
      const std::string& name = "", const Headers& headers = Headers());

  /// Run synchronous inference on server.
  /// \param result Returns the result of inference.
  /// \param options The options for inference request.
  /// \param inputs The vector of InferInput describing the model inputs.
  /// \param outputs Optional vector of InferRequestedOutput describing how the
  /// output must be returned. If not provided then all the outputs in the model
  /// config will be returned as default settings.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the
  /// request.
  Error Infer(
      InferResult** result, const InferOptions& options,
      const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs =
          std::vector<const InferRequestedOutput*>(),
      const Headers& headers = Headers());

  /// Run asynchronous inference on server.
  /// Once the request is completed, the InferResult pointer will be passed to
  /// the provided 'callback' function. Upon the invocation of callback
  /// function, the ownership of InferResult object is transfered to the
  /// function caller. It is then the caller's choice on either retrieving the
  /// results inside the callback function or deferring it to a different thread
  /// so that the client is unblocked. In order to prevent memory leak, user
  /// must ensure this object gets deleted.
  /// \param callback The callback function to be invoked on request completion.
  /// \param options The options for inference request.
  /// \param inputs The vector of InferInput describing the model inputs.
  /// \param outputs Optional vector of InferRequestedOutput describing how the
  /// output must be returned. If not provided then all the outputs in the model
  /// config will be returned as default settings.
  /// \param headers Optional map specifying additional HTTP headers to include
  /// in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error AsyncInfer(
      OnCompleteFn callback, const InferOptions& options,
      const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs =
          std::vector<const InferRequestedOutput*>(),
      const Headers& headers = Headers());

  /// Starts a grpc bi-directional stream to send streaming inferences.
  /// \param callback The callback function to be invoked on receiving a
  /// response at the stream.
  /// \param enable_stats Indicates whether client library should record the
  /// the client-side statistics for inference requests on stream or not.
  /// The library does not support client side statistics for decoupled
  /// streaming. Set this option false when there is no 1:1 mapping between
  /// request and response on the stream.
  /// \param stream_timeout Specifies the end-to-end timeout for the streaming
  /// connection in microseconds. The default value is 0 which means that
  /// there is no limitation on deadline. The stream will be closed once
  /// the specified time elapses.
  /// \param headers Optional map specifying additional HTTP headers to
  /// include in the metadata of gRPC request.
  /// \return Error object indicating success or failure of the request.
  Error StartStream(
      OnCompleteFn callback, bool enable_stats = true,
      uint32_t stream_timeout = 0, const Headers& headers = Headers());

  /// Stops an active grpc bi-directional stream, if one available.
  /// \return Error object indicating success or failure of the request.
  Error StopStream();

  /// Runs an asynchronous inference over gRPC bi-directional streaming
  /// API. A stream must be established with a call to StartStream()
  /// before calling this function. All the results will be provided to the
  /// callback function provided when starting the stream.
  /// \param options The options for inference request.
  /// \param inputs The vector of InferInput describing the model inputs.
  /// \param outputs Optional vector of InferRequestedOutput describing how the
  /// output must be returned. If not provided then all the outputs in the model
  /// config will be returned as default settings.
  /// \return Error object indicating success or failure of the request.
  Error AsyncStreamInfer(
      const InferOptions& options, const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs =
          std::vector<const InferRequestedOutput*>());

 private:
  InferenceServerGrpcClient(
      const std::string& url, bool verbose, bool use_ssl,
      const SslOptions& ssl_options);
  Error PreRunProcessing(
      const InferOptions& options, const std::vector<InferInput*>& inputs,
      const std::vector<const InferRequestedOutput*>& outputs);
  void AsyncTransfer();
  void AsyncStreamTransfer();

  // The producer-consumer queue used to communicate asynchronously with
  // the GRPC runtime.
  grpc::CompletionQueue async_request_completion_queue_;

  // Required to support the grpc bi-directional streaming API.
  InferenceServerClient::OnCompleteFn stream_callback_;
  std::thread stream_worker_;
  std::shared_ptr<
      grpc::ClientReaderWriter<ModelInferRequest, ModelStreamInferResponse>>
      grpc_stream_;
  grpc::ClientContext grpc_context_;

  bool enable_stream_stats_;
  std::queue<std::unique_ptr<RequestTimers>> ongoing_stream_request_timers_;
  std::mutex stream_mutex_;

  // GRPC end point.
  std::unique_ptr<GRPCInferenceService::Stub> stub_;
  // request for GRPC call, one request object can be used for multiple calls
  // since it can be overwritten as soon as the GRPC send finishes.
  ModelInferRequest infer_request_;
};


}}}  // namespace nvidia::inferenceserver::client
