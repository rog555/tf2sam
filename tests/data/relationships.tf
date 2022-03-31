resource "aws_api_gateway_rest_api" "foo" {
    name = "foo"
    binary_media_types = []
}
resource "aws_api_gateway_resource" "foo_bar_resource" {
    parent_id = "${aws_api_gateway_rest_api.foo.root_resource_id}"
    rest_api_id = "${aws_api_gateway_rest_api.foo.id}"
    path_part="bar"
}
resource "aws_api_gateway_resource" "foo_bar_resource_proxy" {
    parent_id = "${aws_api_gateway_resource.foo_bar_resource.id}"
    rest_api_id = "${aws_api_gateway_rest_api.foo.id}"
    path_part="{proxy+}"
}
resource "aws_api_gateway_method" "foo_integration_foo_bar_resource_ANY" {
    http_method  = "ANY"
    authorization = "NONE"
    rest_api_id = "${aws_api_gateway_rest_api.foo.id}"
    resource_id = "${aws_api_gateway_resource.foo_bar_resource_proxy.id}"
}
resource "aws_api_gateway_integration" "foo_integration_foo_bar_resource_ANY_int" {
    resource_id = "${aws_api_gateway_resource.foo_bar_resource_proxy.id}"
    uri = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/${aws_lambda_function.foo_bar-api.arn}/invocations"
    http_method = "${aws_api_gateway_method.foo_integration_foo_bar_resource_ANY.http_method}"
    integration_http_method = "POST"
    rest_api_id = "${aws_api_gateway_rest_api.foo.id}"
    credentials = "${aws_iam_role.foo_gateway-invoke-lambda.arn}"
    type = "AWS_PROXY"
    request_templates = { "application/json" = "{ \"statusCode\": 200 }" }
}
resource "aws_api_gateway_base_path_mapping" "foo_bar-base-path-mapping" {
    base_path            = "foo"
    api_id               = "${aws_api_gateway_rest_api.foo.id}"
    stage_name           = "sandbox2"
    domain_name          = "api.acmecorp.com"
    depends_on           = [ "aws_api_gateway_deployment.foo_bar" ]
}
resource "aws_api_gateway_deployment" "foo_bar" {
    stage_name           = "sandbox2"
    rest_api_id          = "${aws_api_gateway_rest_api.foo.id}"
    depends_on           = ["aws_api_gateway_integration.foo_integration_foo_bar_resource_ANY_int"]
}
