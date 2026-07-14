# Cloudflare config for freecad.virtastic.app (the FreeCAD-WASM deploy on the shared OVH VPS).
# Manages DNS + edge caching declaratively. The Origin Certificate is handled separately
# (dashboard, or a scoped origin-CA step) since it needs a different credential than the API token.
#
# Auth: export CLOUDFLARE_API_TOKEN=... (a token scoped to the virtastic.app zone with
#   Zone:Read, DNS:Edit, Cache Rules:Edit, Zone Settings:Edit). Then: terraform init && terraform apply

terraform {
  required_version = ">= 1.5"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.30"
    }
  }
}

provider "cloudflare" {
  # Reads CLOUDFLARE_API_TOKEN from the environment (do NOT commit the token).
}

data "cloudflare_zone" "this" {
  name = var.zone_name
}

# DNS: freecad.virtastic.app -> the OVH VPS, proxied (orange cloud) so Cloudflare fronts it.
resource "cloudflare_record" "freecad" {
  zone_id = data.cloudflare_zone.this.id
  name    = "freecad"
  type    = "A"
  content = var.origin_ip
  proxied = true
  ttl     = 1 # 1 = automatic (required when proxied)
  comment = "FreeCAD-WASM on the shared OVH VPS (managed by terraform)"
}

# NOTE: SSL mode (Full strict) is set once at the zone level (shared with the other sites) and is
# NOT managed here — `cloudflare_zone_settings_override` reads ALL ~40 zone settings and errors if
# the token can't read a newer one, which makes it unusable. Set it out-of-band if needed.

# Edge caching: cache the immutable engine assets aggressively; let HTML respect origin no-cache.
# The origin (container nginx) already sends correct Cache-Control; this is the edge optimization.
resource "cloudflare_ruleset" "cache" {
  zone_id = data.cloudflare_zone.this.id
  name    = "freecad-cache"
  kind    = "zone"
  phase   = "http_request_cache_settings"

  rules {
    ref         = "freecad_assets"
    description = "Cache-everything for freecad.virtastic.app immutable assets"
    expression  = "(http.host eq \"${var.hostname}\" and http.request.uri.path.extension in {\"wasm\" \"data\" \"js\" \"css\" \"png\" \"svg\"})"
    action      = "set_cache_settings"
    enabled     = true
    action_parameters {
      cache = true
      edge_ttl {
        mode    = "override_origin"
        default = 2592000 # 30 days at the edge for the big immutable blobs
      }
      browser_ttl {
        mode = "respect_origin" # honor the origin's Cache-Control (immutable / no-cache)
      }
    }
  }
}
