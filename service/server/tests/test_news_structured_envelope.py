"""Synthetic structural regressions; no retained customer/model output or API calls."""
import copy
import json

import pytest

from news_quality import REVIEW_SCHEMA
from news_structured_envelope import FUNCTION_NAME, request_contract, result
from news_json import parse


REVIEW = dict(faithful=True, fluent_hebrew=True, unsupported_claims=False,
              duplicate_of=0, material_new_fact=False, explanation='Checked evidence.')


def envelope(arguments=None):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'content': None, 'tool_calls': [{'type': 'function', 'function': {
            'name': FUNCTION_NAME,
            'arguments': json.dumps(REVIEW) if arguments is None else arguments,
        }}],
    }}]}


def test_request_preserves_schema_and_requires_single_output():
    schema = copy.deepcopy(REVIEW_SCHEMA)
    contract = request_contract(schema)
    function = contract['tools'][0]['function']
    assert function['parameters'] == REVIEW_SCHEMA
    assert function['strict'] is True
    assert contract['tool_choice']['function']['name'] == FUNCTION_NAME
    assert 'parallel_tool_calls' not in contract
    assert contract['provider']['require_parameters'] is True
    assert 'response_format' not in contract
    schema['required'].clear()
    assert function['parameters'] == REVIEW_SCHEMA


def test_single_schema_valid_result_does_not_rewrite_quality_fields():
    assert result(envelope(), REVIEW_SCHEMA) == REVIEW
    rejected = {**REVIEW, 'faithful': False, 'unsupported_claims': True}
    assert result(envelope(json.dumps(rejected)), REVIEW_SCHEMA) == rejected


@pytest.mark.parametrize('suffix', [
    ' commentary', '\n</unexpected-marker>\n', '\n' + json.dumps(REVIEW),
    '\ncommentary\n' + json.dumps({**REVIEW, 'explanation': 'Different explanation.'}),
])
def test_never_salvages_first_object_from_invalid_arguments(suffix):
    with pytest.raises(ValueError, match='invalid_structured_arguments'):
        result(envelope(json.dumps(REVIEW) + suffix), REVIEW_SCHEMA)


@pytest.mark.parametrize('arguments', [
    '{}', '[]', 'null', '{"faithful":true,"faithful":false}',
    '{"faithful":NaN}', json.dumps({**REVIEW, 'faithful': 'true'}),
    json.dumps({**REVIEW, 'extra': 'value'}), '{', 'x' * 65537,
    'א' * 40000, '```json\n' + json.dumps(REVIEW) + '\n```',
], ids=['empty-object', 'array', 'null', 'duplicate-key', 'nan', 'wrong-type',
        'extra-key', 'incomplete', 'oversize-ascii', 'oversize-utf8', 'fence'])
def test_invalid_arguments_fail_closed(arguments):
    with pytest.raises(ValueError):
        result(envelope(arguments), REVIEW_SCHEMA)


@pytest.mark.parametrize('case', [
    'no_choices', 'two_choices', 'length', 'stop', 'refusal', 'prose',
    'json_content', 'no_calls', 'two_calls', 'wrong_name', 'wrong_type',
    'arguments_object', 'message_list',
])
def test_envelope_ambiguity_fails_closed(case):
    body = envelope()
    choice = body['choices'][0]
    message = choice['message']
    call = message['tool_calls'][0]
    if case == 'no_choices': body['choices'] = []
    elif case == 'two_choices': body['choices'].append(copy.deepcopy(choice))
    elif case in {'length', 'stop'}: choice['finish_reason'] = case
    elif case == 'refusal': message['refusal'] = 'Cannot comply'
    elif case == 'prose': message['content'] = 'Different result follows'
    elif case == 'json_content': message['content'] = json.dumps(REVIEW)
    elif case == 'no_calls': message['tool_calls'] = []
    elif case == 'two_calls': message['tool_calls'].append(copy.deepcopy(call))
    elif case == 'wrong_name': call['function']['name'] = 'execute_trade'
    elif case == 'wrong_type': call['type'] = 'action'
    elif case == 'arguments_object': call['function']['arguments'] = REVIEW
    elif case == 'message_list': choice['message'] = []
    with pytest.raises(ValueError):
        result(body, REVIEW_SCHEMA)


def test_current_parser_still_rejects_observed_shapes():
    text = json.dumps(REVIEW)
    for malformed in (text + ' prose ' + text,
                      text + '\"}\n</malformed marker\n' + text,
                      text + ' prose ' + json.dumps({**REVIEW, 'explanation': 'Changed.'})):
        with pytest.raises(ValueError):
            parse(malformed)
