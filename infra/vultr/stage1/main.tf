data "vultr_os" "debian" {
  filter {
    name   = "name"
    values = [var.os_name]
  }
}

resource "vultr_ssh_key" "me" {
  name    = "${var.name}-key"
  ssh_key = var.ssh_public_key
}

# ---------------------------------------------------------------------------
# Firewall for the control-plane VM.
#   22, 8000 : admin only (SSH, and the raw API port for your own testing)
#   80, 443  : open to the world, so judges can reach the HTTPS API front door
#              that we add in the portal/auth phase. Nothing listens there yet.
# VKE worker nodes are left on Vultr's defaults; public traffic reaches apps
# through the Traefik load balancer that Stage 2 creates.
# ---------------------------------------------------------------------------
resource "vultr_firewall_group" "cp" {
  description = "${var.name} control plane"
}

locals {
  admin_rules = {
    for pair in setproduct(["22", "8000"], var.admin_cidrs) :
    "${pair[0]}-${pair[1]}" => { port = pair[0], cidr = pair[1] }
  }
}

resource "vultr_firewall_rule" "admin" {
  for_each          = local.admin_rules
  firewall_group_id = vultr_firewall_group.cp.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = split("/", each.value.cidr)[0]
  subnet_size       = tonumber(split("/", each.value.cidr)[1])
  port              = each.value.port
  notes             = "admin ${each.value.port}"
}

resource "vultr_firewall_rule" "public_web" {
  for_each          = toset(["80", "443"])
  firewall_group_id = vultr_firewall_group.cp.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = each.value
  notes             = "public web ${each.value}"
}

# ---------------------------------------------------------------------------
# Control-plane VM (Debian). cloud-init installs Docker, PostgreSQL, git and
# Python tooling and creates the `idp` service user and /etc/idp.
# ---------------------------------------------------------------------------
resource "vultr_instance" "cp" {
  label             = "${var.name}-control-plane"
  hostname          = "${var.name}-cp"
  region            = var.region
  plan              = var.cp_plan
  os_id             = data.vultr_os.debian.id
  ssh_key_ids       = [vultr_ssh_key.me.id]
  firewall_group_id = vultr_firewall_group.cp.id
  enable_ipv6       = false
  backups           = "disabled"
  tags              = [var.name, "control-plane"]

  user_data = base64encode(templatefile("${path.module}/../../cloud-init/control-plane.yaml.tftpl", {
    hostname = "${var.name}-cp"
  }))
}

# ---------------------------------------------------------------------------
# Managed Kubernetes (the control plane is free; you pay for nodes + load
# balancers). Stage 2 installs Flux and Traefik into this cluster.
# ---------------------------------------------------------------------------
resource "vultr_kubernetes" "vke" {
  region  = var.region
  label   = "${var.name}-vke"
  version = var.k8s_version

  node_pools {
    node_quantity = var.node_count
    plan          = var.node_plan
    label         = "workers"
  }
}

# ---------------------------------------------------------------------------
# PRIVATE container registry (spec section 6). Pulling needs credentials, and
# so does pushing. Credentials never go in Git; see outputs.tf.
# ---------------------------------------------------------------------------
resource "vultr_container_registry" "vcr" {
  name   = var.registry_name
  region = var.registry_region
  plan   = var.registry_plan
  public = false
}
