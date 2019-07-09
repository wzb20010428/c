// Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
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

#include <string>
#include <unordered_map>

#include "src/backends/custom/custom.h"
#include "src/core/model_config.h"
#include "src/core/model_config.pb.h"
#include "src/custom/sdk/error_codes.h"

namespace nvidia { namespace inferenceserver { namespace custom {

// Base class for custom backend instances
// Responsible for the state of the instance and used to provide a
// C++ wrapper around the C-API
class CustomInstance {
 public:
  static int Create(
      CustomInstance** instance, const std::string& name,
      const ModelConfig& model_config, int gpu_device,
      const CustomInitializeData* data);

  virtual ~CustomInstance() = default;

  // Perform custom execution on the payloads
  virtual int Execute(
      const uint32_t payload_cnt, CustomPayload* payloads,
      CustomGetNextInputFn_t input_fn, CustomGetOutputFn_t output_fn) = 0;

  inline const char* ErrorString(uint32_t error) const {
    return errors_.ErrorString(error).c_str();
  }

 protected:
  CustomInstance(
      const std::string& instance_name, const ModelConfig& model_config,
      int gpu_device);

  // The name of this backend instance
  const std::string instance_name_;

  // The model configuration
  const ModelConfig model_config_;

  // The GPU device ID to execute on or CUSTOM_NO_GPU_DEVICE if should
  // execute on CPU.
  const int gpu_device_;

  // Error code manager
  ErrorCodes errors_;

 private:
  // An overridable method to add error strings for additional custom errors
  virtual const char* CustomErrorString(int errcode);
};

}}}  // namespace nvidia::inferenceserver::custom