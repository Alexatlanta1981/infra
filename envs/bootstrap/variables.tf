variable "github_repo_subject_prefixes" {
  description = "Map of repo name to its OIDC sub-claim prefix"
  type        = map(string)
  default = {
    infra    = "repo:Alexatlanta1981@336695319/infra@1392205632"
    backend  = "repo:Alexatlanta1981@336695319/backend@1391441917"
    frontend = "repo:Alexatlanta1981@336695319/frontend@1391441426"
    gitops   = "repo:Alexatlanta1981@336695319/gitops@1392209866"
  }
}
