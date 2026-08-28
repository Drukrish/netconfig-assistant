# Deploys the actual FastAPI app on ECS Fargate - RDS alone (main.tf) is
# only half of "the app runs on AWS." No ALB: this is a portfolio/demo
# deployment meant to be shown to interviewers on demand, not a production
# service needing a stable domain and HTTPS - a direct public IP on the
# Fargate task is the honest minimum for that, not a corner cut silently.
# Add an ALB + ACM cert later if a stable URL ever matters.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_ecr_repository" "app" {
  name         = "netconfig-assistant"
  force_delete = true # portfolio repo, no retention policy needed
}

# Secrets live in SSM as SecureString, referenced by ARN in the task
# definition's `secrets` block - never as plaintext `environment` entries,
# which anyone with ecs:DescribeTaskDefinition (a very common read
# permission) could otherwise read straight off.
resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/netconfig-assistant/anthropic_api_key"
  type  = "SecureString"
  value = var.anthropic_api_key
}

resource "aws_ssm_parameter" "database_url" {
  name  = "/netconfig-assistant/database_url"
  type  = "SecureString"
  value = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.netconfig.endpoint}/netconfig"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/netconfig-assistant"
  retention_in_days = 7 # portfolio deployment, not production - keep log cost near zero
}

resource "aws_ecs_cluster" "app" {
  name = "netconfig-assistant"
}

# Fargate's own execution role - distinct from a task role: this is what AWS
# uses to pull the image from ECR and write logs, not what the app itself
# assumes. AmazonECSTaskExecutionRolePolicy alone can't read our SSM
# parameters, hence the extra inline policy below.
resource "aws_iam_role" "ecs_execution" {
  name = "netconfig-assistant-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_ssm_read" {
  name = "netconfig-assistant-ssm-read"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = [aws_ssm_parameter.anthropic_api_key.arn, aws_ssm_parameter.database_url.arn]
    }]
  })
}

resource "aws_security_group" "ecs_app" {
  name        = "netconfig-assistant-app"
  description = "Public access to the deployed netconfig-assistant app on port 8000"

  ingress {
    description = "App API, public - this is a demo deployment meant to be reachable"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = "netconfig-assistant"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256" # smallest Fargate size - this is a demo workload, not production traffic
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([
    {
      name         = "app"
      image        = "${aws_ecr_repository.app.repository_url}:latest"
      essential    = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn },
        { name = "ANTHROPIC_API_KEY", valueFrom = aws_ssm_parameter.anthropic_api_key.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "app"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "app" {
  name            = "netconfig-assistant"
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.ecs_app.id]
    assign_public_ip = true
  }

  # RDS must exist and be reachable before the app starts, or its lifespan
  # startup hook (Base.metadata.create_all) fails hard on first boot.
  depends_on = [aws_db_instance.netconfig]
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.app.name
}

output "ecs_service_name" {
  value = aws_ecs_service.app.name
}
