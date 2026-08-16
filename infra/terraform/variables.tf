variable "zone_name" {
  description = "Cloudflare zone (root domain)"
  type        = string
  default     = "virtastic.app"
}

variable "hostname" {
  description = "Public hostname for the deploy"
  type        = string
  default     = "freecad.virtastic.app"
}

# No default on purpose: Cloudflare proxies the hostname so the origin stays private,
# and this repo is public. Supply it out of band:  export TF_VAR_origin_ip=<vps-ipv4>
variable "origin_ip" {
  description = "Origin server (OVH VPS) IPv4 — supply via TF_VAR_origin_ip, never commit"
  type        = string
}
