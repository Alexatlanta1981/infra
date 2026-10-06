mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

run "fresh_account_bootstrap" {
  command = plan

  variables {
    github_repo_subject_prefixes = {
      infra    = "repo:example-owner@111111/infra@222221"
      backend  = "repo:example-owner@111111/backend@222222"
      frontend = "repo:example-owner@111111/frontend@222223"
      gitops   = "repo:example-owner@111111/gitops@222224"
    }
  }
}
