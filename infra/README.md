# infra: Terraform for the mini-IDP

Drop this folder next to your repos (it needs none of their code). **Never commit state or secrets**: `.gitignore` covers it.

## The idea: two stages, one contract
```
vultr/stage1/   VM + VKE + registry + firewall      }  provider-specific
proxmox/stage1/ two VMs cloned from your template   }  (rehearsal)
stage2/         Flux bootstrap + Traefik + reads the load-balancer IP     <- identical for both
scripts/        up / down / kubeconfig / gen-env / push
```
Both environments end by producing the same things: a kubeconfig, a registry URL, an ingress IP, a control-plane VM.
`scripts/gen-env.sh` turns those into the control plane's `.env`.

## Rehearsal (Proxmox), one time setup
1. `cp proxmox/stage1/terraform.tfvars.example proxmox/stage1/terraform.tfvars` and fill it in.
2. `cp stage2/proxmox.tfvars.example stage2/proxmox.tfvars`. `cp env/secrets.example env/proxmox.secrets` and fill in.
3. Create a private GitOps repo (push your `idp-gitops-manifests` contents; branch `main`).
4. `export TF_VAR_pm_api_token=... TF_VAR_git_token=<PAT>` then `scripts/up.sh proxmox`
5. `scripts/push.sh proxmox`, ssh in, clone the control plane, `pip install`, run it (see its README).
6. Drill: `scripts/down.sh proxmox` -> `scripts/up.sh proxmox` until you can do it without notes. Time each step.

Use `TF=tofu scripts/up.sh ...` if you use OpenTofu.

**Assumptions about your packer template:** cloud-init works, k3s is the `k3s` systemd unit. Snippets must be enabled on the
`snippet_datastore` (Datacenter > Storage > Content). If the first boot misbehaves, those are the first suspects.
k3s already ships Traefik, so `install_traefik = false` there.

## Hackathon (Vultr)
1. Vultr: Account > API > enable, then **Access Control**: add the venue's public IP (or temporarily "Allow all IPv4"). Export `VULTR_API_KEY`. Never put it on the VM or give it to teammates.
2. `scripts/vke-versions.sh` -> paste the newest into `vultr/stage1/terraform.tfvars` (copy the .example).
3. `cp stage2/vultr.tfvars.example stage2/vultr.tfvars`; `cp env/secrets.example env/vultr.secrets`.
4. `scripts/up.sh vultr`. **Registry push credentials are not a Terraform output**: when it finishes, copy the registry's username and API key from the Vultr console
   into `env/vultr.secrets`, then rerun `scripts/gen-env.sh vultr`.
5. `scripts/push.sh vultr` (`SSH_PORT=443` if the venue blocks 22; cloud-init makes sshd listen on both). No SSH at all? Use the Vultr web console.
6. After the weekend: `scripts/down.sh vultr`, check the dashboard for leftover Load Balancers, **delete the API key**.

## Verified vs not
Checked with OpenTofu against the real provider schemas: Vultr, Proxmox, Flux all `validate`; the Vultr plan expands correctly; cloud-init renders to valid YAML in both modes.
**Not run:** anything that talks to Vultr/Proxmox/a cluster, and the `helm`/`kubernetes` providers in stage2 (not obtainable in my sandbox).
Expect to fix small things on first contact. Notes: `ufw` is allowed for 22/443/8000 in case the image ships it enabled; the VKE version is intentionally not defaulted.
