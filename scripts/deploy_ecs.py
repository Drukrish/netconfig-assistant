"""Build, push, and roll out the app image to ECS Fargate. Terraform (ecs.tf)
owns the infrastructure; this script owns the application image, since
Terraform doesn't build Docker images itself - `terraform apply` alone
would create the ECS service pointing at an image tag that doesn't exist
yet.

Run with: python scripts/deploy_ecs.py
Requires: docker, aws CLI configured with credentials that can push to ECR
and update the ECS service (the same terraform-netconfig IAM user, plus
whatever ECR/ECS permissions were attached for this).
"""

import subprocess
import sys

REGION = "ap-south-1"
CLUSTER = "netconfig-assistant"
SERVICE = "netconfig-assistant"
ECR_REPO = "netconfig-assistant"


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kwargs)


def main() -> None:
    account_id = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    registry = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com"
    image = f"{registry}/{ECR_REPO}:latest"

    print(f"Deploying to account {account_id}, region {REGION}")

    login_pw = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", REGION],
        check=True, capture_output=True, text=True,
    ).stdout
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=login_pw, check=True, text=True,
    )

    run(["docker", "build", "-t", image, "."])
    run(["docker", "push", image])

    # Fargate pulls whatever the running task definition points at, which
    # doesn't change just because a new image landed under the same tag -
    # force-new-deployment tells ECS to actually re-pull and restart.
    run([
        "aws", "ecs", "update-service",
        "--cluster", CLUSTER, "--service", SERVICE,
        "--force-new-deployment", "--region", REGION,
    ])

    print("\nDeployment triggered. Check status with:")
    print(f"  aws ecs describe-services --cluster {CLUSTER} --services {SERVICE} --region {REGION}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        sys.exit(1)
