"""Strict output envelope for canonical news only.

The function is an output envelope, never an executable tool. No network, retry,
model selection, budget handling or trading actions live here. Other AI paths
keep their existing response_format.
Do not extract a preferred JSON object from malformed free-form content.
"""
import copy
import json

import jsonschema

FUNCTION_NAME = 'submit_news_result'
MAX_ARGUMENT_BYTES = 65536


def request_contract(schema):
    """Alternative to response_format, not an additional agent/tool-use loop."""
    jsonschema.Draft202012Validator.check_schema(schema)
    return {
        'tools': [{'type': 'function', 'function': {
            'name': FUNCTION_NAME,
            'description': 'Submit the single structured news result; no actions are executed.',
            'strict': True,
            'parameters': copy.deepcopy(schema),
        }}],
        'tool_choice': {'type': 'function', 'function': {'name': FUNCTION_NAME}},
        # Luna endpoints do not advertise parallel_tool_calls. Enforce the
        # single-result rule in result(), without an unsupported wire parameter.
        'provider': {'require_parameters': True},
    }


def output_instruction():
    return ('Submit exactly one result using submit_news_result. Its arguments must '
            'match the supplied schema. Do not put JSON, explanations or a second '
            'result in message content. Do not call any other function.')


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_key')
        value[key] = item
    return value


def _constant(_):
    raise ValueError('non_finite_json_number')


def result(body, schema):
    """Fail closed on mixed content, extra choices/tools, refusals and truncation.

    Returned values still require the unchanged independent quality review.
    A valid envelope is not approval to publish. Error strings contain no output.
    """
    if not isinstance(body, dict):
        raise ValueError('invalid_response_structure')
    choices = body.get('choices')
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError('invalid_response_structure')
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError('invalid_response_structure')
    if choice.get('finish_reason') == 'length':
        raise ValueError('ai_output_truncated')
    if choice.get('finish_reason') != 'tool_calls':
        raise ValueError('structured_envelope_required')
    message = choice.get('message')
    if not isinstance(message, dict) or message.get('refusal'):
        raise ValueError('structured_envelope_required')
    content = message.get('content')
    if content is not None and (not isinstance(content, str) or content.strip()):
        raise ValueError('ambiguous_response_content')
    calls = message.get('tool_calls')
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError('single_structured_result_required')
    call = calls[0]
    if not isinstance(call, dict) or call.get('type') != 'function':
        raise ValueError('structured_envelope_required')
    function = call.get('function')
    if not isinstance(function, dict) or function.get('name') != FUNCTION_NAME:
        raise ValueError('unexpected_output_function')
    arguments = function.get('arguments')
    if (not isinstance(arguments, str) or len(arguments) > MAX_ARGUMENT_BYTES or
            len(arguments.encode('utf-8')) > MAX_ARGUMENT_BYTES):
        raise ValueError('invalid_structured_arguments')
    try:
        value = json.loads(arguments, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        raise ValueError('invalid_structured_arguments') from None
    if not isinstance(value, dict):
        raise ValueError('ai_object_required')
    try:
        jsonschema.validate(value, schema)
    except jsonschema.ValidationError:
        raise ValueError('schema_validation_failed') from None
    return value
