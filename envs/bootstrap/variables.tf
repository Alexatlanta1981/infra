variable "github_repo_subject_prefixes" {
  description = "Map of repo name to its OIDC sub-claim prefix, e.g. repo:ORG@ORGID/infra@REPOID per repo. Generate with scripts/00_oidc_subjects.sh"
  type        = map(string)
}
