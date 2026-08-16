output "db_endpoint" {
  value = aws_db_instance.netconfig.endpoint
}

output "database_url" {
  value     = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.netconfig.endpoint}/netconfig"
  sensitive = true
}
