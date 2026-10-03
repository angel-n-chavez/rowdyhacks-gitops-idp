output "control_plane_ip" {
  description = "Public IPv4 of the control-plane VM."
  value       = vultr_instance.cp.main_ip
}

output "vke_cluster_id" {
  value = vultr_kubernetes.vke.id
}

output "vke_endpoint" {
  value = vultr_kubernetes.vke.endpoint
}

output "kubeconfig" {
  description = "Admin kubeconfig for VKE. Sensitive: scripts/kubeconfig.sh writes it to ~/.kube, never to the repo."
  value       = base64decode(vultr_kubernetes.vke.kube_config)
  sensitive   = true
}

output "registry_host" {
  value = "${var.registry_region}.vultrcr.com"
}

output "registry_name" {
  value = vultr_container_registry.vcr.name
}

output "image_prefix" {
  description = "Spec section 15: images are <image_prefix>/<app-name>:<short-sha>."
  value       = "${var.registry_region}.vultrcr.com/${vultr_container_registry.vcr.name}"
}

output "registry_root_user" {
  description = "Registry root credentials as returned by Vultr (map). Sensitive: read with `output -json registry_root_user`."
  value       = vultr_container_registry.vcr.root_user
  sensitive   = true
}
