import json
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT_DIR, 'tests', 'data')
sys.path.append(ROOT_DIR)

import tf2sam as ts  # noqa: E402


def test_relationships():
    data = ts.load_file(os.path.join(DATA_DIR, 'relationships.tf'))
    actual = ts.get_relationships(data['resource'])
    print(json.dumps(actual, indent=2))
    assert actual == json.loads('''
{
  "aws_api_gateway_rest_api.foo": {
    "aws_api_gateway_resource": [
      "foo_bar_resource",
      "foo_bar_resource_proxy"
    ],
    "aws_api_gateway_method": [
      "foo_integration_foo_bar_resource_ANY"
    ],
    "aws_api_gateway_integration": [
      "foo_integration_foo_bar_resource_ANY_int"
    ],
    "aws_api_gateway_base_path_mapping": [
      "foo_bar-base-path-mapping"
    ],
    "aws_api_gateway_deployment": [
      "foo_bar"
    ]
  },
  "aws_api_gateway_resource.foo_bar_resource": {
    "aws_api_gateway_rest_api": [
      "foo"
    ],
    "aws_api_gateway_resource": [
      "foo_bar_resource_proxy"
    ]
  },
  "aws_api_gateway_resource.foo_bar_resource_proxy": {
    "aws_api_gateway_resource": [
      "foo_bar_resource"
    ],
    "aws_api_gateway_rest_api": [
      "foo"
    ],
    "aws_api_gateway_method": [
      "foo_integration_foo_bar_resource_ANY"
    ],
    "aws_api_gateway_integration": [
      "foo_integration_foo_bar_resource_ANY_int"
    ]
  },
  "aws_api_gateway_method.foo_integration_foo_bar_resource_ANY": {
    "aws_api_gateway_rest_api": [
      "foo"
    ],
    "aws_api_gateway_resource": [
      "foo_bar_resource_proxy"
    ],
    "aws_api_gateway_integration": [
      "foo_integration_foo_bar_resource_ANY_int"
    ]
  },
  "aws_api_gateway_integration.foo_integration_foo_bar_resource_ANY_int": {
    "aws_api_gateway_resource": [
      "foo_bar_resource_proxy"
    ],
    "aws_lambda_function": [
      "foo_bar-api"
    ],
    "aws_api_gateway_method": [
      "foo_integration_foo_bar_resource_ANY"
    ],
    "aws_api_gateway_rest_api": [
      "foo"
    ],
    "aws_iam_role": [
      "foo_gateway-invoke-lambda"
    ]
  },
  "aws_lambda_function.foo_bar-api": {
    "aws_api_gateway_integration": [
      "foo_integration_foo_bar_resource_ANY_int"
    ]
  },
  "aws_iam_role.foo_gateway-invoke-lambda": {
    "aws_api_gateway_integration": [
      "foo_integration_foo_bar_resource_ANY_int"
    ]
  },
  "aws_api_gateway_base_path_mapping.foo_bar-base-path-mapping": {
    "aws_api_gateway_rest_api": [
      "foo"
    ]
  },
  "aws_api_gateway_deployment.foo_bar": {
    "aws_api_gateway_rest_api": [
      "foo"
    ]
  }
}
''')
