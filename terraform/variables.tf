variable "aws_region" {
  type    = string
  default = "ap-south-1" # Mumbai - closest region, cuts cross-region latency for local testing
}

variable "db_username" {
  type    = string
  default = "netconfig"
}

variable "db_password" {
  type      = string
  sensitive = true
  # No default on purpose - must come from a real secret (terraform.tfvars,
  # never committed, or TF_VAR_db_password in the environment), same
  # discipline as never reading .env directly in this project.
}

variable "allowed_cidr" {
  type        = string
  description = "CIDR allowed to reach Postgres on 5432 - your own IP/32, not 0.0.0.0/0"
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  # Same discipline as db_password: no default, must come from
  # terraform.tfvars (gitignored) or TF_VAR_anthropic_api_key. Stored in SSM
  # as SecureString, not baked into the task definition as plaintext -
  # anyone with ecs:DescribeTaskDefinition read access must not be able to
  # read the key straight off it.
}
