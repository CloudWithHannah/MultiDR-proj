# DR Region — terraform.tfvars
# These are the only values you change day-to-day

enable_nat_gateway = false   # Set to true when activating DR failover

dr_asg_desired = 0           # 0 = no EC2 cost at rest
dr_asg_min     = 0
dr_asg_max     = 3
