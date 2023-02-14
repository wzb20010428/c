#!/usr/bin/env python
# Copyright 2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

sys.path.append(os.path.join(os.environ["TRITON_QA_ROOT_DIR"], "common"))

import numpy as np
import unittest
import time
import shutil
import test_util as tu

import tritonclient.http as httpclient
from tritonclient.utils import InferenceServerException

class ModelNamespacePoll(tu.TestResultCollector):
    def setUp(self):
        self.client_ = httpclient.InferenceServerClient("localhost:8000")

        # Create the data for the two input tensors. Initialize the first
        # to unique integers and the second to all ones.
        self.inputs_ = []
        self.inputs_.append(httpclient.InferInput('INPUT0', [16], "INT32"))
        self.inputs_.append(httpclient.InferInput('INPUT1', [16], "INT32"))

        # Initialize the data
        input_data = np.arange(start=0, stop=16, dtype=np.int32)
        self.inputs_[0].set_data_from_numpy(input_data)
        self.inputs_[1].set_data_from_numpy(input_data)
        self.expected_outputs_ = {
          "add" : (input_data + input_data),
          "sub" : (input_data - input_data)
        }

    def check_health(self, expect_live=True, expect_ready=True):
        self.assertEqual(self.client_.is_server_live(), expect_live)
        self.assertEqual(self.client_.is_server_ready(), expect_ready)

    def test_no_duplication(self):
        # Enable model namspacing on repositories that is already valid without
        # All models should be visible and can be inferred individually
        self.check_health()
        # addsub
        for model in ["simple_addsub", "composing_addsub"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd", "composing_subadd"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])

    def test_duplication(self):
        # Enable model namspacing on repositories that each repo has one
        # ensemble and it requires an composing model ('composing_model') that
        # exists in both repos.
        # Expect all models are visible, the ensemble will pick up the correct
        # model even the composing model can't be inferred individually.
        self.check_health()
        # addsub
        for model in ["simple_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("composing_model", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())

    def test_ensemble_duplication(self):
        # Enable model namspacing on repositories that each repo has one
        # ensemble with the same name. Expect the ensemble will pick up the correct
        # model.
        # Expect all models are visible, the ensemble will pick up the correct
        # model even the ensemble itself can't be inferred without providing
        # namespace.
        self.check_health()
        # addsub
        for model in ["composing_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["composing_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("simple_ensemble", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())

    def test_dynamic_resolution(self):
        # Same model setup as 'test_duplication', will remove / add one of the
        # composing model at runtime and expect the ensemble to be properly
        # linked to exisiting composing model at different steps.
        # 1. Remove 'composing_model' in addsub_repo, expect both ensembles use
        #    'composing_model' in subadd_repo and act as subadd
        # 2. Add back 'composing_model' in addsub_repo, expect the ensembles to behave the
        #    same as before the removal.
        self.assertTrue("NAMESPACE_TESTING_DIRCTORY" in os.environ)
        td = os.environ["NAMESPACE_TESTING_DIRCTORY"]
        composing_before_path = os.path.join(td, "addsub_repo", "composing_model")
        composing_after_path = os.path.join(td, "composing_model")

        self.check_health()
        # step 1.
        shutil.move(composing_before_path, composing_after_path)
        time.sleep(5)
        # subadd
        for model in ["simple_subadd", "simple_addsub", "composing_model"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
  
        # step 2.
        shutil.move(composing_after_path, composing_before_path)
        time.sleep(5)
        # addsub
        for model in ["simple_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("composing_model", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())


class ModelNamespaceExplicit(tu.TestResultCollector):
    def setUp(self):
        self.client_ = httpclient.InferenceServerClient("localhost:8000")

        # Create the data for the two input tensors. Initialize the first
        # to unique integers and the second to all ones.
        self.inputs_ = []
        self.inputs_.append(httpclient.InferInput('INPUT0', [16], "INT32"))
        self.inputs_.append(httpclient.InferInput('INPUT1', [16], "INT32"))

        # Initialize the data
        input_data = np.arange(start=0, stop=16, dtype=np.int32)
        self.inputs_[0].set_data_from_numpy(input_data)
        self.inputs_[1].set_data_from_numpy(input_data)
        self.expected_outputs_ = {
          "add" : (input_data + input_data),
          "sub" : (input_data - input_data)
        }

    def check_health(self, expect_live=True, expect_ready=True):
        self.assertEqual(self.client_.is_server_live(), expect_live)
        self.assertEqual(self.client_.is_server_ready(), expect_ready)

    def test_no_duplication(self):
        # Enable model namspacing on repositories that is already valid without
        # All models should be visible and can be inferred individually
        self.check_health()
        # load ensembles, cascadingly load composing model
        for model in ["simple_addsub", "simple_subadd"]:
            self.client_.load_model(model)

        # addsub
        for model in ["simple_addsub", "composing_addsub"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd", "composing_subadd"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])

    def test_duplication(self):
        # Enable model namspacing on repositories that each repo has one
        # ensemble and it requires an composing model ('composing_model') that
        # exists in both repos.
        # Expect all models are visible, the ensemble will pick up the correct
        # model even the composing model can't be inferred individually.
        self.check_health()
        # load ensembles, cascadingly load composing model
        for model in ["simple_addsub", "simple_subadd"]:
            self.client_.load_model(model)

        # addsub
        for model in ["simple_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("composing_model", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())

    def test_ensemble_duplication(self):
        # Enable model namspacing on repositories that each repo has one
        # ensemble with the same name. Expect the ensemble will pick up the correct
        # model.
        # Expect all models are visible, the ensemble will pick up the correct
        # model even the ensemble itself can't be inferred without providing
        # namespace.
        self.check_health()
        # load ensembles, cascadingly load composing model
        for model in ["simple_ensemble"]:
            self.client_.load_model(model)
        
        # addsub
        for model in ["composing_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["composing_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("simple_ensemble", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())

    def test_dynamic_resolution(self):
        # Same model setup as 'test_duplication', will remove / add one of the
        # composing model at runtime and expect the ensemble to be properly
        # linked to exisiting composing model at different steps.
        # 1. Remove 'composing_model' in addsub_repo, expect both ensembles use
        #    'composing_model' in subadd_repo and act as subadd.
        # 2. Add back 'composing_model' in addsub_repo, expect the ensembles to behave the
        #    same as before the removal.
        self.assertTrue("NAMESPACE_TESTING_DIRCTORY" in os.environ)
        td = os.environ["NAMESPACE_TESTING_DIRCTORY"]
        composing_before_path = os.path.join(td, "addsub_repo", "composing_model")
        composing_after_path = os.path.join(td, "composing_model")

        self.check_health()
        # step 1.
        shutil.move(composing_before_path, composing_after_path)
        # load ensembles, cascadingly load composing model
        for model in ["simple_addsub", "simple_subadd"]:
            self.client_.load_model(model)
        # subadd
        for model in ["simple_subadd", "simple_addsub", "composing_model"]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
  
        # step 2.
        shutil.move(composing_after_path, composing_before_path)
        # Explicitly load one of the ensembel, should still trigger cascading
        # (re-)load
        for model in ["simple_addsub", ]:
            self.client_.load_model(model)
        # addsub
        for model in ["simple_addsub",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["add"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["sub"])
        # subadd
        for model in ["simple_subadd",]:
            res = self.client_.infer(model, self.inputs_)
            np.testing.assert_allclose(res.as_numpy('OUTPUT0'), self.expected_outputs_["sub"])
            np.testing.assert_allclose(res.as_numpy('OUTPUT1'), self.expected_outputs_["add"])
        # error check
        try:
            self.client_.infer("composing_model", self.inputs_)
            self.assertTrue(False,
                            "expected error for inferring ambiguous named model")
        except InferenceServerException as ex:
            self.assertIn("ambiguity", ex.message())


if __name__ == '__main__':
    unittest.main()
