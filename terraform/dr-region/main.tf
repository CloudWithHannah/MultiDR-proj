###############################################################
# Multi-DR Project – Cross-Region Replication (DR Region)
# Project:        nexaflow
# Primary Region: eu-north-1 (Stockholm)
# DR Region:      eu-west-1  (Ireland)
# Domain:         ngozi-opara-portfolio.com
###############################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "multidr-terraform-state-eu-north-1"
    key            = "dr-region/terraform.tfstate"
    region         = "eu-north-1"
    dynamodb_table = "terraform-lock"
    encrypt        = true
  }
}

###############################################################
# PROVIDERS
###############################################################

provider "aws" {
  alias  = "primary"
  region = "eu-north-1"
}

provider "aws" {
  alias  = "dr"
  region = "eu-west-1"
}

# Route53 is a global service — its API always lives in us-east-1
provider "aws" {
  alias  = "route53"
  region = "us-east-1"
}

###############################################################
# LOCALS — all hardcoded primary-region values
# (replaces terraform_remote_state since primary was built manually)
###############################################################

locals {
  # Primary region real values
  primary_alb_dns_name = "multidr-lb-350446221.eu-north-1.elb.amazonaws.com"
  primary_alb_zone_id  = "Z23TAZ6LKFMNIO"
  primary_rds_arn      = "arn:aws:rds:eu-north-1:211125592725:db:multidr-project"

  # Project-wide tags
  dr_tags = {
    Project     = "nexaflow"
    Environment = "production-dr"
    ManagedBy   = "Terraform"
    Region      = "eu-west-1"
  }
}

###############################################################
# DATA SOURCES
###############################################################

data "aws_availability_zones" "dr" {
  provider = aws.dr
  state    = "available"
}

###############################################################
# VPC — DR Region (10.1.0.0/16 mirrors primary 10.0.0.0/16)
###############################################################

resource "aws_vpc" "dr" {
  provider             = aws.dr
  cidr_block           = "10.1.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.dr_tags, { Name = "nexaflow-dr-vpc" })
}

# Public subnet AZ-a — ALB lives here
resource "aws_subnet" "dr_public" {
  provider                = aws.dr
  vpc_id                  = aws_vpc.dr.id
  cidr_block              = "10.1.1.0/24"
  availability_zone       = data.aws_availability_zones.dr.names[0]
  map_public_ip_on_launch = true
  tags                    = merge(local.dr_tags, { Name = "nexaflow-dr-public" })
}

# Public subnet AZ-b — ALB requires at least 2 AZs
resource "aws_subnet" "dr_public_2" {
  provider                = aws.dr
  vpc_id                  = aws_vpc.dr.id
  cidr_block              = "10.1.2.0/24"
  availability_zone       = data.aws_availability_zones.dr.names[1]
  map_public_ip_on_launch = true
  tags                    = merge(local.dr_tags, { Name = "nexaflow-dr-public-2" })
}

# Private app subnet — EC2 instances live here
resource "aws_subnet" "dr_private_app" {
  provider          = aws.dr
  vpc_id            = aws_vpc.dr.id
  cidr_block        = "10.1.10.0/24"
  availability_zone = data.aws_availability_zones.dr.names[0]
  tags              = merge(local.dr_tags, { Name = "nexaflow-dr-private-app" })
}

# Private DB subnet AZ-a — RDS lives here
resource "aws_subnet" "dr_private_db" {
  provider          = aws.dr
  vpc_id            = aws_vpc.dr.id
  cidr_block        = "10.1.20.0/24"
  availability_zone = data.aws_availability_zones.dr.names[0]
  tags              = merge(local.dr_tags, { Name = "nexaflow-dr-private-db" })
}

# Private DB subnet AZ-b — RDS subnet group requires 2 AZs
resource "aws_subnet" "dr_private_db_2" {
  provider          = aws.dr
  vpc_id            = aws_vpc.dr.id
  cidr_block        = "10.1.21.0/24"
  availability_zone = data.aws_availability_zones.dr.names[1]
  tags              = merge(local.dr_tags, { Name = "nexaflow-dr-private-db-2" })
}

###############################################################
# INTERNET GATEWAY
###############################################################

resource "aws_internet_gateway" "dr" {
  provider = aws.dr
  vpc_id   = aws_vpc.dr.id
  tags     = merge(local.dr_tags, { Name = "nexaflow-dr-igw" })
}

###############################################################
# NAT GATEWAY
# Disabled by default (saves ~$32/month while DR is on standby)
# Set enable_nat_gateway = true in terraform.tfvars on failover
###############################################################

resource "aws_eip" "dr_nat" {
  count    = var.enable_nat_gateway ? 1 : 0
  provider = aws.dr
  domain   = "vpc"
  tags     = merge(local.dr_tags, { Name = "nexaflow-dr-nat-eip" })
}

resource "aws_nat_gateway" "dr" {
  count         = var.enable_nat_gateway ? 1 : 0
  provider      = aws.dr
  allocation_id = aws_eip.dr_nat[0].id
  subnet_id     = aws_subnet.dr_public.id
  depends_on    = [aws_internet_gateway.dr]
  tags          = merge(local.dr_tags, { Name = "nexaflow-dr-nat" })
}

###############################################################
# ROUTE TABLES
###############################################################

resource "aws_route_table" "dr_public" {
  provider = aws.dr
  vpc_id   = aws_vpc.dr.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dr.id
  }

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-rt-public" })
}

resource "aws_route_table_association" "dr_public" {
  provider       = aws.dr
  subnet_id      = aws_subnet.dr_public.id
  route_table_id = aws_route_table.dr_public.id
}

resource "aws_route_table_association" "dr_public_2" {
  provider       = aws.dr
  subnet_id      = aws_subnet.dr_public_2.id
  route_table_id = aws_route_table.dr_public.id
}

resource "aws_route_table" "dr_private" {
  provider = aws.dr
  vpc_id   = aws_vpc.dr.id

  # Route only exists when NAT Gateway is enabled (failover mode)
  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.dr[0].id
    }
  }

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-rt-private" })
}

resource "aws_route_table_association" "dr_private_app" {
  provider       = aws.dr
  subnet_id      = aws_subnet.dr_private_app.id
  route_table_id = aws_route_table.dr_private.id
}

###############################################################
# SECURITY GROUPS
###############################################################

# ALB — accepts HTTP/HTTPS from the internet
resource "aws_security_group" "dr_alb" {
  provider    = aws.dr
  name        = "nexaflow-dr-alb-sg"
  description = "DR ALB: allow inbound HTTP and HTTPS from internet"
  vpc_id      = aws_vpc.dr.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-alb-sg" })
}

# App — only accepts traffic from the ALB on port 5000
resource "aws_security_group" "dr_app" {
  provider    = aws.dr
  name        = "nexaflow-dr-app-sg"
  description = "DR App: allow port 5000 from ALB only"
  vpc_id      = aws_vpc.dr.id

  ingress {
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.dr_alb.id]
  }

  # HTTPS inbound from VPC for SSM VPC endpoints
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.1.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-app-sg" })
}

# DB — only accepts PostgreSQL from the app security group
resource "aws_security_group" "dr_db" {
  provider    = aws.dr
  name        = "nexaflow-dr-db-sg"
  description = "DR DB: allow PostgreSQL from app only"
  vpc_id      = aws_vpc.dr.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.dr_app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-db-sg" })
}

###############################################################
# SSM VPC ENDPOINTS
# Required because DR instances are in a private subnet with
# no NAT Gateway at rest. These let SSM reach instances
# privately without internet access.
###############################################################

resource "aws_vpc_endpoint" "dr_ssm" {
  provider            = aws.dr
  vpc_id              = aws_vpc.dr.id
  service_name        = "com.amazonaws.eu-west-1.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.dr_private_app.id]
  security_group_ids  = [aws_security_group.dr_app.id]
  private_dns_enabled = true
  tags                = merge(local.dr_tags, { Name = "nexaflow-dr-ssm-endpoint" })
}

resource "aws_vpc_endpoint" "dr_ssmmessages" {
  provider            = aws.dr
  vpc_id              = aws_vpc.dr.id
  service_name        = "com.amazonaws.eu-west-1.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.dr_private_app.id]
  security_group_ids  = [aws_security_group.dr_app.id]
  private_dns_enabled = true
  tags                = merge(local.dr_tags, { Name = "nexaflow-dr-ssmmessages-endpoint" })
}

resource "aws_vpc_endpoint" "dr_ec2messages" {
  provider            = aws.dr
  vpc_id              = aws_vpc.dr.id
  service_name        = "com.amazonaws.eu-west-1.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.dr_private_app.id]
  security_group_ids  = [aws_security_group.dr_app.id]
  private_dns_enabled = true
  tags                = merge(local.dr_tags, { Name = "nexaflow-dr-ec2messages-endpoint" })
}

###############################################################
# RDS CROSS-REGION READ REPLICA
# Continuously replicates from the primary RDS instance.
# On failover: aws rds promote-read-replica
###############################################################

resource "aws_db_subnet_group" "dr" {
  provider   = aws.dr
  name       = "nexaflow-dr-db-subnet-group"
  subnet_ids = [aws_subnet.dr_private_db.id, aws_subnet.dr_private_db_2.id]
  tags       = merge(local.dr_tags, { Name = "nexaflow-dr-db-subnet-group" })
}

resource "aws_db_instance" "dr_replica" {
  provider   = aws.dr
  identifier = "nexaflow-dr-replica"
  kms_key_id = "arn:aws:kms:eu-west-1:211125592725:key/7c1690a6-304d-424f-86cc-a6ec027e5fb9"

  # Points directly to the primary RDS ARN across regions
  replicate_source_db = local.primary_rds_arn

  instance_class      = "db.t4g.micro"
  storage_encrypted   = true
  publicly_accessible = false
  skip_final_snapshot = true

  db_subnet_group_name   = aws_db_subnet_group.dr.name
  vpc_security_group_ids = [aws_security_group.dr_db.id]

  # Read replicas inherit backup settings from primary
  backup_retention_period = 0

  auto_minor_version_upgrade = true
  deletion_protection        = true

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-replica" })
}

###############################################################
# APPLICATION LOAD BALANCER — DR
###############################################################

resource "aws_lb" "dr" {
  provider           = aws.dr
  name               = "nexaflow-dr-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.dr_alb.id]

  # Two public subnets required by ALB
  subnets = [
    aws_subnet.dr_public.id,
    aws_subnet.dr_public_2.id
  ]

  tags = merge(local.dr_tags, { Name = "nexaflow-dr-alb" })
}

resource "aws_lb_target_group" "dr" {
  provider    = aws.dr
  name        = "nexaflow-dr-tg"
  port        = 5000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.dr.id
  target_type = "instance"

  health_check {
    path                = "/health"
    port                = "5000"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = local.dr_tags
}

resource "aws_lb_listener" "dr_http" {
  provider          = aws.dr
  load_balancer_arn = aws_lb.dr.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dr.arn
  }
}

###############################################################
# IAM ROLE FOR DR EC2 INSTANCES
###############################################################

data "aws_iam_policy_document" "dr_ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dr_app" {
  provider           = aws.dr
  name               = "nexaflow-dr-app-role"
  assume_role_policy = data.aws_iam_policy_document.dr_ec2_assume.json
  tags               = local.dr_tags
}

resource "aws_iam_role_policy_attachment" "dr_ssm" {
  provider   = aws.dr
  role       = aws_iam_role.dr_app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "dr_cw_agent" {
  provider   = aws.dr
  role       = aws_iam_role.dr_app.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "dr_app" {
  provider = aws.dr
  name     = "nexaflow-dr-app-profile"
  role     = aws_iam_role.dr_app.name
}

###############################################################
# LAUNCH TEMPLATE
# Uses the golden AMI copied from the primary Ubuntu instance.
# This means the DR instance is an exact clone — same OS,
# same app, same dependencies — nothing needs reinstalling.
###############################################################

resource "aws_launch_template" "dr" {
  provider      = aws.dr
  name_prefix   = "nexaflow-dr-lt-"
  image_id      = "ami-035a98b7a055ac419"   # Golden AMI copied from primary (eu-west-1)
  instance_type = "t3.micro"

  iam_instance_profile {
    name = aws_iam_instance_profile.dr_app.name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.dr_app.id]
    subnet_id                   = aws_subnet.dr_private_app.id
  }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    # Restart the app service on first boot
    # Everything is already installed in the golden AMI
    systemctl daemon-reload
    systemctl enable myapp
    systemctl start myapp
  EOF
  )

  monitoring { enabled = true }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.dr_tags, { Name = "nexaflow-dr-app" })
  }

  lifecycle { create_before_destroy = true }
}

###############################################################
# AUTO SCALING GROUP
# min=0 at rest (no EC2 cost). Scale to 1 on failover.
###############################################################

resource "aws_autoscaling_group" "dr" {
  provider            = aws.dr
  name                = "nexaflow-dr-asg"
  desired_capacity    = var.dr_asg_desired   # 0 normally
  min_size            = var.dr_asg_min        # 0 normally
  max_size            = var.dr_asg_max        # 3 max
  vpc_zone_identifier = [aws_subnet.dr_private_app.id]
  target_group_arns   = [aws_lb_target_group.dr.arn]

  # Use EC2 health check at rest (no app running when ASG=0)
  # Switch to ELB once app is deployed after failover
  health_check_type = "EC2"

  launch_template {
    id      = aws_launch_template.dr.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "nexaflow-dr-app"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = "nexaflow"
    propagate_at_launch = true
  }
}

###############################################################
# ROUTE53 — Health Check + Failover DNS
# Domain: ngozi-opara-portfolio.com
# Hosted Zone ID: Z094031728F4ZD8DF8NZ6
###############################################################

# Health check watches the primary ALB every 30 seconds
resource "aws_route53_health_check" "primary" {
  provider          = aws.route53
  fqdn              = local.primary_alb_dns_name
  port              = 80
  type              = "HTTP"
  resource_path     = "/health"
  failure_threshold = 3
  request_interval  = 30

  tags = merge(local.dr_tags, { Name = "nexaflow-primary-health-check" })
}

# PRIMARY record — Route53 sends traffic here when primary is healthy
resource "aws_route53_record" "primary" {
  provider       = aws.route53
  zone_id        = "Z094031728F4ZD8DF8NZ6"
  name           = "nexaflow.ngozi-opara-portfolio.com"
  type           = "A"
  set_identifier = "primary"

  failover_routing_policy {
    type = "PRIMARY"
  }

  alias {
    name                   = local.primary_alb_dns_name
    zone_id                = local.primary_alb_zone_id
    evaluate_target_health = true
  }

  health_check_id = aws_route53_health_check.primary.id
}

# SECONDARY record — Route53 activates this when primary health check fails
resource "aws_route53_record" "dr" {
  provider       = aws.route53
  zone_id        = "Z094031728F4ZD8DF8NZ6"
  name           = "nexaflow.ngozi-opara-portfolio.com"
  type           = "A"
  set_identifier = "secondary"

  failover_routing_policy {
    type = "SECONDARY"
  }

  alias {
    name                   = aws_lb.dr.dns_name
    zone_id                = aws_lb.dr.zone_id
    evaluate_target_health = true
  }
}

###############################################################
# S3 CROSS-REGION REPLICATION
# Primary bucket in eu-north-1, replica in eu-west-1
###############################################################

resource "aws_s3_bucket" "primary_assets" {
  provider = aws.primary
  bucket   = "nexaflow-assets-primary-eu-north-1"
  tags     = local.dr_tags
}

resource "aws_s3_bucket_versioning" "primary_assets" {
  provider = aws.primary
  bucket   = aws_s3_bucket.primary_assets.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket" "dr_assets" {
  provider = aws.dr
  bucket   = "nexaflow-assets-dr-eu-west-1"
  tags     = local.dr_tags
}

resource "aws_s3_bucket_versioning" "dr_assets" {
  provider = aws.dr
  bucket   = aws_s3_bucket.dr_assets.id
  versioning_configuration { status = "Enabled" }
}

data "aws_iam_policy_document" "s3_replication_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "s3_replication" {
  provider           = aws.primary
  name               = "nexaflow-s3-replication-role"
  assume_role_policy = data.aws_iam_policy_document.s3_replication_assume.json
}

resource "aws_iam_role_policy" "s3_replication" {
  provider = aws.primary
  name     = "nexaflow-s3-replication-policy"
  role     = aws_iam_role.s3_replication.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
        Resource = [aws_s3_bucket.primary_assets.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObjectVersionForReplication", "s3:GetObjectVersionAcl", "s3:GetObjectVersionTagging"]
        Resource = ["${aws_s3_bucket.primary_assets.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags"]
        Resource = ["${aws_s3_bucket.dr_assets.arn}/*"]
      }
    ]
  })
}

resource "aws_s3_bucket_replication_configuration" "assets" {
  provider   = aws.primary
  depends_on = [aws_s3_bucket_versioning.primary_assets]
  role       = aws_iam_role.s3_replication.arn
  bucket     = aws_s3_bucket.primary_assets.id

  rule {
    id     = "replicate-all"
    status = "Enabled"
    destination {
      bucket        = aws_s3_bucket.dr_assets.arn
      storage_class = "STANDARD_IA"   # Cheaper storage class for DR copies
    }
  }
}

###############################################################
# MONITORING — DR Region
###############################################################

resource "aws_sns_topic" "dr_alerts" {
  provider = aws.dr
  name     = "nexaflow-dr-alerts"
  tags     = local.dr_tags
}

resource "aws_sns_topic_subscription" "dr_email" {
  provider  = aws.dr
  topic_arn = aws_sns_topic.dr_alerts.arn
  protocol  = "email"
  endpoint  = "ngozihannahopara@gmail.com"
}

# Fires if DR replica falls more than 5 minutes behind primary
resource "aws_cloudwatch_metric_alarm" "dr_replica_lag" {
  provider            = aws.dr
  alarm_name          = "nexaflow-dr-replica-lag"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ReplicaLag"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 300
  alarm_actions       = [aws_sns_topic.dr_alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.dr_replica.id
  }

  tags = local.dr_tags
}

# Fires if DR ALB returns more than 10 errors per minute
resource "aws_cloudwatch_metric_alarm" "dr_alb_5xx" {
  provider            = aws.dr
  alarm_name          = "nexaflow-dr-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_actions       = [aws_sns_topic.dr_alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.dr.arn_suffix
  }

  tags = local.dr_tags
}

## Fires when primary health check fails — confirms failover has been triggered
#resource "aws_cloudwatch_metric_alarm" "primary_health_failed" {
#  provider            = aws.route53
#  alarm_name          = "nexaflow-primary-health-check-failed"
#  comparison_operator = "LessThanThreshold"
#  evaluation_periods  = 1
#  metric_name         = "HealthCheckStatus"
#  namespace           = "AWS/Route53"
#  period              = 60
#  statistic           = "Minimum"
#  threshold           = 1
#  alarm_actions       = [aws_sns_topic.dr_alerts.arn]
#  treat_missing_data  = "notBreaching"
#
#  dimensions = {
#    HealthCheckId = aws_route53_health_check.primary.id
#  }
#
#  tags = local.dr_tags
#}

###############################################################
# VPC FLOW LOGS — DR Region
###############################################################

resource "aws_cloudwatch_log_group" "dr_flow_logs" {
  provider          = aws.dr
  name              = "/aws/vpc/flowlogs/nexaflow-dr"
  retention_in_days = 30
  tags              = local.dr_tags
}

data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dr_flow_logs" {
  provider           = aws.dr
  name               = "nexaflow-dr-flow-logs-role"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json
  tags               = local.dr_tags
}

resource "aws_iam_role_policy" "dr_flow_logs" {
  provider = aws.dr
  name     = "nexaflow-dr-flow-logs-policy"
  role     = aws_iam_role.dr_flow_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "dr_vpc" {
  provider        = aws.dr
  iam_role_arn    = aws_iam_role.dr_flow_logs.arn
  log_destination = aws_cloudwatch_log_group.dr_flow_logs.arn
  traffic_type    = "ALL"
  vpc_id          = aws_vpc.dr.id
  tags            = local.dr_tags
}

###############################################################
# OUTPUTS
###############################################################

output "dr_alb_dns_name" {
  description = "DR ALB DNS name — used for smoke tests and manual verification"
  value       = aws_lb.dr.dns_name
}

output "dr_replica_endpoint" {
  description = "DR RDS replica endpoint — update app config on failover"
  value       = aws_db_instance.dr_replica.address
}

output "dr_vpc_id" {
  description = "DR VPC ID"
  value       = aws_vpc.dr.id
}

output "domain_primary_record" {
  description = "Your domain now points to the primary ALB. DR activates automatically on failure."
  value       = "ngozi-opara-portfolio.com → ${local.primary_alb_dns_name} (PRIMARY)"
}
