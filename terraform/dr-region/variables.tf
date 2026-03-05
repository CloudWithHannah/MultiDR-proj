variable "enable_nat_gateway" {
  description = "Set to true during DR failover to give instances outbound internet access"
  type        = bool
  default     = false
}

variable "dr_asg_desired" {
  description = "Desired EC2 instances in DR ASG. 0 at rest, 1 on failover."
  type        = number
  default     = 0
}

variable "dr_asg_min" {
  description = "Minimum EC2 instances in DR ASG"
  type        = number
  default     = 0
}

variable "dr_asg_max" {
  description = "Maximum EC2 instances in DR ASG"
  type        = number
  default     = 3
}
