terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "c3-experiment"
      Owner     = "oleksandr-vakhula"
      Purpose   = "cose-revision-validation"
      ManagedBy = "terraform"
      # Дозволяє знайти і знести ВСЕ одним фільтром, якщо terraform state загубиться
      KillSwitch = "true"
    }
  }
}
