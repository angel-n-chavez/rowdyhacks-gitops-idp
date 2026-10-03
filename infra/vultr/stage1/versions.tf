terraform {
  required_version = ">= 1.5"
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.32"
    }
  }
}

# The API key is read from the VULTR_API_KEY environment variable.
# It is full-account scope: never put it in a file, on the VM, or in git.
provider "vultr" {
  rate_limit  = 100
  retry_limit = 3
}
