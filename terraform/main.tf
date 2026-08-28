# Single free-tier-eligible RDS Postgres instance with pgvector, replacing
# the local docker-compose Postgres for a deployed environment. pgvector
# needs no parameter-group changes on RDS (unlike extensions that need
# shared_preload_libraries) - just `CREATE EXTENSION vector;` after the
# instance is up, same as the local setup in ingest.py.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_security_group" "rds" {
  name        = "netconfig-assistant-rds"
  description = "Allows Postgres access to the netconfig-assistant RDS instance"

  ingress {
    description = "Postgres from the allowed CIDR only"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  # The deployed app (ecs.tf) needs to reach this same database - referencing
  # the ECS task's own security group here, not a second CIDR rule, means
  # only that specific task can connect, not "anything on the app's subnet."
  ingress {
    description     = "Postgres from the deployed ECS app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "netconfig" {
  identifier     = "netconfig-assistant"
  engine         = "postgres"
  engine_version = "16"

  # db.t3.micro + 20GB gp2 is the free-tier-eligible shape for the first 12
  # months of an AWS account - see ContentHandoff.md's open item: confirm
  # the account is still inside that window before `terraform apply`.
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_type      = "gp2"

  db_name  = "netconfig"
  username = var.db_username
  password = var.db_password

  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = true
  skip_final_snapshot    = true

  # Dev/portfolio infra, not production - single-AZ keeps it inside the
  # free tier. A real production deployment would flip this and add a
  # final-snapshot policy instead of skip_final_snapshot.
  multi_az = false
}
