# Cloudflare Terraform — freecad.virtastic.app

Declaratively manages the `virtastic.app` Cloudflare config for the FreeCAD-WASM deploy: the DNS
record (A -> the OVH VPS, proxied) and the edge cache rule. Same pattern as openmw-wasm/ja2-web.

## What it does NOT do
- **Origin Certificate** — needs the Cloudflare *Origin CA key* (different credential from the API
  token). Already installed on the box for the shared edge (`/opt/edge/certs/virtastic.*`), covering
  `*.virtastic.app`, so freecad reuses it — nothing to do here.
- **SSL mode** — set once at the zone level (Full strict), shared across all sites.

## Auth + apply
Create/reuse a Cloudflare **API token** scoped to the `virtastic.app` zone with:
`Zone:Read`, `DNS:Edit`, `Cache Rules:Edit`. Then:

```bash
export CLOUDFLARE_API_TOKEN=<your-token>
cd infra/terraform
terraform init
terraform plan      # review — should show 1 DNS record + 1 cache ruleset to add
terraform apply
```

State is local and gitignored (`*.tfstate`). Override any input via `-var` or a `terraform.tfvars`.
Once applied, `https://freecad.virtastic.app` resolves through Cloudflare to the box.
