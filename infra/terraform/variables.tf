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

variable "origin_ip" {
  description = "Origin server (OVH VPS) IPv4"
  type        = string
  default     = "ORIGIN-IP-REDACTED"
}
