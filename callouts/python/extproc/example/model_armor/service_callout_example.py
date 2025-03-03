# Copyright 2025 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
from typing import Tuple

from envoy.service.ext_proc.v3 import external_processor_pb2 as service_pb2
from envoy.type.v3 import http_status_pb2
from extproc.service import callout_server, callout_tools
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1
from grpc import ServicerContext


def screen_prompt(prompt: str) -> Tuple[bool, str]:
    """Screen prompt with model armour.

    Args:
        prompt (str): The prompt to check.
    """

    # Initialize prompt validation status and final prompt
    is_invalid = False
    final_prompt = prompt

    # Location for model armor client and template
    location = os.environ.get("MA_LOCATION")

    # Create the model armor client
    client = modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(
            api_endpoint=f"modelarmor.{location}.rep.googleapis.com"
        ),
    )

    # Model Armor prompt template
    model_armour_template = os.environ.get("MA_PROMPT_TEMPLATE")

    # Get the findings for prompt
    sanitize_response = client.sanitize_user_prompt(
        request=modelarmor_v1.SanitizeUserPromptRequest(
            name=model_armour_template,
            user_prompt_data=modelarmor_v1.DataItem(text=prompt),
        )
    )

    # Check if Match Found for any filter
    if (
        sanitize_response.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    ):
        # If De-identify SDP filter is matched, get the sanitized text from model armor
        if (
            sanitize_response.sanitization_result.filter_results.get(
                "sdp"
            ).sdp_filter_result.deidentify_result.match_state
            == modelarmor_v1.FilterMatchState.MATCH_FOUND
        ):
            final_prompt = (
                sanitize_response.sanitization_result.filter_results.get(
                    "sdp"
                ).sdp_filter_result.deidentify_result.data.text
                or prompt
            )
        # Mark prompt invalid for other filter match
        else:
            is_invalid = True

    # Return final finding and original/sanitized prompt
    return is_invalid, final_prompt


def screen_model_response(model_response: str) -> Tuple[bool, str]:
    """Screen model response with model armour.

    Args:
        response (str): The response to check.
    """
    # Initialize model response validation status and final response text
    is_invalid = False
    final_model_response = model_response

    # Location for model armor client and template
    location = os.environ.get("MA_LOCATION")

    # Create the model armor client
    client = modelarmor_v1.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(
            api_endpoint=f"modelarmor.{location}.rep.googleapis.com"
        ),
    )

    # Model Armor prompt template
    model_armour_template = os.environ.get("MA_RESPONSE_TEMPLATE")

    # Get the findings for model response
    sanitize_model_response = client.sanitize_model_response(
        request=modelarmor_v1.SanitizeUserPromptRequest(
            name=model_armour_template,
            user_prompt_data=modelarmor_v1.DataItem(text=final_model_response),
        )
    )

    # Check if Match Found for any filter
    if (
        sanitize_model_response.sanitization_result.filter_match_state
        == modelarmor_v1.FilterMatchState.MATCH_FOUND
    ):
        # If De-identify SDP filter is matched, get the sanitized text from model armor
        if (
            sanitize_model_response.sanitization_result.filter_results.get(
                "sdp"
            ).sdp_filter_result.deidentify_result.match_state
            == modelarmor_v1.FilterMatchState.MATCH_FOUND
        ):
            final_model_response = (
                sanitize_model_response.sanitization_result.filter_results.get(
                    "sdp"
                ).sdp_filter_result.deidentify_result.data.text
            )
        # Mark prompt invalid for other filter match
        else:
            is_invalid = True

    # Return final finding and original/sanitized prompt
    return is_invalid, final_model_response


class CalloutServerExample(callout_server.CalloutServer):
    """Example callout server with external screening service integration."""

    def on_request_body(self, body: service_pb2.HttpBody, context: ServicerContext):
        """Custom processor on the request body.

        Args:
            body (service_pb2.HttpBody): The HTTP body received in the request.
            context (ServicerContext): The context object for the gRPC service.

        Returns:
            service_pb2.BodyResponse: The response containing the mutations to be applied
            to the request body.
        """
        body_content = f"{body.body.decode('utf-8')}".strip()
        if not body_content:
            return callout_tools.add_body_mutation()

        body_json = json.loads(body_content)
        prompt = body_json.get("prompt", "")

        if not prompt:
            return callout_tools.add_body_mutation()
        is_invalid_prompt, valid_prompt = screen_prompt(prompt)
        if is_invalid_prompt:
            # Stop request for invalid prompts
            return callout_tools.header_immediate_response(
                code=http_status_pb2.StatusCode.Forbidden,
                headers=[
                    (
                        "model-armour-message",
                        "Provided prompt does not comply with Responsible AI filter",
                    )
                ],
            )

        body_json["prompt"] = valid_prompt
        return callout_tools.add_body_mutation(body=json.dumps(body_json))

    def on_response_body(self, body: service_pb2.HttpBody, context: ServicerContext):
        """Custom processor on the response body.

        Args:
            body (service_pb2.HttpBody): The HTTP body received in the response.
            context (ServicerContext): The context object for the gRPC service.

        Returns:
            service_pb2.BodyResponse: The response containing the mutations to be applied
            to the response body.
        """
        body_content = f"{body.body.decode('utf-8')}".strip()
        if not body_content:
            return callout_tools.add_body_mutation()
        print(f"Raw JSON Input: {body_content!r}")

        response_body_json = json.loads(body_content)
        model_response = response_body_json["choices"][0]["message"]["content"]

        if not model_response:
            return callout_tools.add_body_mutation()

        is_invalid_model_response, valid_model_response = screen_prompt(model_response)
        if is_invalid_model_response:
            # Stop response for invalid model response
            return callout_tools.deny_callout(
                context,
                msg="Model response violates responsible AI filters. Update the prompt or contact application admin if issue persists.",
            )

        response_body_json["choices"][0]["message"]["content"] = valid_model_response
        return callout_tools.add_body_mutation(body=json.dumps(response_body_json))


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Run the gRPC service
    CalloutServerExample().run()
