variable "project" { type = string }
variable "env" { type = string }
variable "aws_account_id" { type = string }
variable "infra_repo" {
  type    = string
  default = "infra"
}
variable "github_repo_subject_prefixes" { type = map(string) }
