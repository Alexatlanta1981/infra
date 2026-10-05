resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "/mackllc/${var.env}/db-config"
  description             = "Non-secret database connection settings; the password lives in the RDS-managed secret"
  recovery_window_in_days = 0

  tags = {
    Name    = "/mackllc/${var.env}/db-config"
    Env     = var.env
    Project = var.project
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    host     = var.db_host
  })
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name                    = "/mackllc/${var.env}/jwt-secret"
  description             = "JWT signing secret for the mackllc ${var.env} environment"
  recovery_window_in_days = 0

  tags = {
    Name    = "/mackllc/${var.env}/jwt-secret"
    Env     = var.env
    Project = var.project
  }
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id = aws_secretsmanager_secret.jwt_secret.id
  secret_string = jsonencode({
    secret = var.jwt_secret
  })
}
