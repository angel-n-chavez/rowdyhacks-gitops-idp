variable "name" {
  type        = string
  default     = "rowdyhacks"
  description = "Prefix for resource labels."
}

variable "region" {
  type        = string
  default     = "ewr"
  description = "Vultr region for the VM and the VKE cluster."
}

variable "ssh_public_key" {
  type        = string
  description = "Your SSH public key (contents of ~/.ssh/id_ed25519.pub)."

  validation {
    condition     = can(regex("^ssh-", var.ssh_public_key))
    error_message = "ssh_public_key must be a public key that starts with 'ssh-' (ssh-ed25519 / ssh-rsa)."
  }
}

variable "admin_cidrs" {
  type        = list(string)
  description = "IPv4 CIDRs allowed to reach SSH (22) and the raw API port (8000). Example: [\"203.0.113.7/32\"]"

  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for c in var.admin_cidrs : can(cidrnetmask(c))])
    error_message = "admin_cidrs must be a non-empty list of valid IPv4 CIDRs, e.g. 203.0.113.7/32."
  }
}

variable "k8s_version" {
  type        = string
  description = "VKE Kubernetes version. Run scripts/vultr-lookups.sh versions and paste one, e.g. v1.xx.x+1."
}

variable "node_plan" {
  type    = string
  default = "vc2-2c-4gb"
}

variable "node_count" {
  type    = number
  default = 2

  validation {
    condition     = var.node_count >= 1
    error_message = "node_count must be at least 1."
  }
}

variable "cp_plan" {
  type        = string
  default     = "vc2-2c-4gb"
  description = "Control-plane VM size. It runs FastAPI, PostgreSQL and Docker builds, so keep at least 4 GB RAM."
}

variable "os_name" {
  type        = string
  default     = "Debian 12 x64 (bookworm)"
  description = "Exact Vultr OS name for the control-plane VM. List names with scripts/vultr-lookups.sh os."
}

variable "registry_name" {
  type        = string
  default     = "rowdyhacks"
  description = "Registry name. It must be globally unique across Vultr and becomes the middle segment of every image path (<host>/<registry_name>/<app>:<sha>)."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*$", var.registry_name))
    error_message = "registry_name must be lowercase letters, digits and hyphens."
  }
}

variable "registry_region" {
  type    = string
  default = "ewr"
}

variable "registry_plan" {
  type    = string
  default = "start_up"
}
