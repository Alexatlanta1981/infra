terraform {
  backend "s3" {
    key          = "envs/bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
