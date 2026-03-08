# NexaFlow — Multi-Region Disaster Recovery on AWS

A production-grade web application deployed across two AWS regions with automated failover, CI/CD pipeline, and infrastructure-as-code. Built to demonstrate real disaster recovery patterns used in enterprise environments.

**Live:** [nexaflow.ngozi-opara-portfolio.com](http://nexaflow.ngozi-opara-portfolio.com)

-----

## What This Project Does

NexaFlow is a Flask web application running in AWS Stockholm (`eu-north-1`) with a full standby environment in AWS Ireland (`eu-west-1`). If the primary region becomes unavailable, Route53 detects the failure and automatically reroutes traffic to the DR region — no manual intervention needed for DNS failover.

The entire infrastructure is defined in Terraform and deployed through a Jenkins CI/CD pipeline. Application changes pushed to GitHub trigger an automated build, test, and deploy cycle.

-----

## Architecture

```
Internet
    │
    ▼
Route53 (Health Check + Failover Routing)
    │
    ├── PRIMARY: eu-north-1 (Stockholm)
    │       │
    │       ▼
    │   Application Load Balancer
    │       │
    │       ▼
    │   Auto Scaling Group (EC2 t3.micro, private subnet)
    │       │
    │       ▼
    │   Flask App (Gunicorn, port 5000)
    │       │
    │       ▼
    │   RDS PostgreSQL (private subnet, encrypted)
    │       │
    │       └── Cross-region replication ──────────────┐
    │                                                   │
    └── DR STANDBY: eu-west-1 (Ireland)                │
            │                                           │
            ▼                                           ▼
        Application Load Balancer              RDS Read Replica
            │
            ▼
        Auto Scaling Group (min=0 at rest)
            │
            ▼
        Flask App (Golden AMI — pre-installed)
```

### Key design decisions

**Private subnets for compute** — EC2 instances and RDS have no public IPs. All inbound traffic enters through the ALB. Outbound traffic routes through a NAT Gateway. This limits the attack surface significantly.

**Golden AMI for DR** — Instead of running a bootstrap script on every new instance, the DR launch template uses a pre-built AMI that already has the OS, dependencies, and application installed. A new DR instance is ready to serve traffic within the instance boot time, not boot time plus install time.

**NAT Gateway disabled at rest in DR** — The DR region costs roughly $52/month when active. With `enable_nat_gateway = false` in `terraform.tfvars`, there is no NAT Gateway charge while the DR region is on standby. Setting it to `true` during a failover event restores full outbound connectivity.

**RDS cross-region read replica** — The replica receives a continuous stream of changes from the primary. On failover, one command promotes it to a standalone writable instance: `aws rds promote-read-replica`.

-----

## Tech Stack

|Layer                 |Technology                                                                                        |
|----------------------|--------------------------------------------------------------------------------------------------|
|Cloud                 |AWS (EC2, RDS, ALB, ASG, Route53, VPC, IAM, CloudWatch, SNS, S3, Secrets Manager, Systems Manager)|
|Infrastructure as Code|Terraform 1.6+                                                                                    |
|CI/CD                 |Jenkins (Pipeline as Code)                                                                        |
|Application           |Python 3, Flask, Gunicorn                                                                         |
|Database              |PostgreSQL 15 on Amazon RDS                                                                       |
|Source Control        |Git, GitHub                                                                                       |
|Alerting              |CloudWatch Alarms → SNS → Email + Slack                                                           |

-----

## Repository Structure

```
MultiDR-proj/
├── app/
│   └── app.py                  # Flask application
├── terraform/
│   └── dr-region/
│       ├── main.tf             # All DR infrastructure
│       ├── variables.tf        # Variable definitions
│       └── terraform.tfvars    # Environment values
├── Jenkinsfile                 # CI/CD pipeline definition
├── .gitignore
└── README.md
```

-----

## Infrastructure Components

### Primary Region (eu-north-1) — built manually

|Component        |Details                                                     |
|-----------------|------------------------------------------------------------|
|VPC              |10.0.0.0/16 with public, private-app, and private-db subnets|
|EC2              |t3.micro in private subnet, managed by ASG                  |
|ALB              |Public-facing, HTTP:80 → forwards to EC2:5000               |
|RDS              |PostgreSQL db.t4g.micro, encrypted, private subnet          |
|NAT Gateway      |Gives private instances outbound internet access            |
|SSM VPC Endpoints|Allows Session Manager access without a bastion host        |

### DR Region (eu-west-1) — managed by Terraform

|Component     |Details                                      |
|--------------|---------------------------------------------|
|VPC           |10.1.0.0/16, mirrors primary layout          |
|ASG           |min=0, max=3 — zero EC2 cost at rest         |
|ALB           |Ready but idle until failover                |
|RDS Replica   |Continuously replicates from primary         |
|S3 Replication|Assets bucket replicated from primary to DR  |
|NAT Gateway   |Created only when `enable_nat_gateway = true`|

-----

## CI/CD Pipeline

The Jenkins pipeline runs on the primary EC2 instance and has six stages:

```
Checkout → Terraform Validate → Terraform Plan → Approval → Terraform Apply → Deploy App → Smoke Test
```

**Approval gate** — the pipeline pauses after `terraform plan` and waits for a human to review the proposed changes before applying them. This prevents accidental infrastructure changes from being deployed automatically.

**Smoke test** — after deployment, the pipeline hits `/health` and checks for a `200` response. If the health check fails, the pipeline marks the build as failed and sends a Slack alert.

**Slack notifications** — build results are posted to a Slack channel via incoming webhook, regardless of whether the build passed or failed.

-----

## Application Endpoints

|Endpoint |Method|Description                                   |
|---------|------|----------------------------------------------|
|`/`      |GET   |NexaFlow landing page                         |
|`/health`|GET   |System status page (browser) or JSON (API/ALB)|
|`/users` |GET   |List all users from RDS                       |
|`/users` |POST  |Create a new user                             |

The `/health` endpoint detects whether it is being called by a browser or a programmatic client. Browsers get a styled status dashboard. The ALB health checker and `curl` get plain JSON:

```json
{
  "status": "healthy",
  "db": "connected"
}
```

-----

## Secrets Management

Database credentials are never stored in code, environment variables, or the repository. At runtime, the application calls AWS Secrets Manager to retrieve the RDS username, password, host, and port. Credential rotation happens transparently without redeploying the application.

-----

## Monitoring and Alerting

CloudWatch alarms fire on the following conditions and send email and Slack notifications via SNS:

|Alarm               |Threshold                               |
|--------------------|----------------------------------------|
|EC2 CPU utilisation |> 80% for 5 minutes                     |
|ALB 5XX error count |> 10 per minute                         |
|RDS replica lag     |> 5 minutes behind primary              |
|Route53 health check|Primary ALB failing 3 consecutive checks|

-----

## Failover Procedure

When the primary region goes down:

1. **Automatic** — Route53 health check detects failure after 3 missed checks (90 seconds)
1. **Automatic** — DNS failover switches `nexaflow.ngozi-opara-portfolio.com` to the DR ALB
1. **Manual** — Scale up the DR ASG: set `dr_asg_desired = 1` in `terraform.tfvars` and run `terraform apply`
1. **Manual** — Enable NAT Gateway: set `enable_nat_gateway = true` and run `terraform apply`
1. **Manual** — Promote the RDS replica: `aws rds promote-read-replica --db-instance-identifier nexaflow-dr-replica`

Steps 3-5 can be automated with a Lambda function triggered by the Route53 health check alarm. This is a planned improvement.

-----

## Local Development

### Prerequisites

- AWS CLI configured with appropriate permissions
- Terraform 1.6+
- Python 3.10+

### Deploy DR Infrastructure

```bash
cd terraform/dr-region
terraform init
terraform plan
terraform apply
```

### Activate DR Failover

```bash
# terraform.tfvars
enable_nat_gateway = true
dr_asg_desired     = 1
```

```bash
terraform apply
aws rds promote-read-replica \
  --db-instance-identifier nexaflow-dr-replica \
  --region eu-west-1
```

### Tear Down DR Region

```bash
terraform destroy
```

Destroys all DR infrastructure cleanly. The primary region is unaffected. Rebuild any time with `terraform apply`.

-----

## Lessons Learned

This project involved real troubleshooting of real AWS issues. Some of the more instructive ones:

- **ALB listener port vs target group port** — the ALB listens on port 80 (public-facing) and forwards to port 5000 (internal). These are separate settings that must both be configured correctly.
- **Route table associations** — public subnets must point to the Internet Gateway; private subnets must point to the NAT Gateway. Swapping them silently breaks both inbound and outbound connectivity in different ways.
- **SSM depends on NAT** — EC2 instances in private subnets need either a NAT Gateway or SSM VPC endpoints to reach the SSM service. Without one of these, Session Manager stops working.
- **Terraform state locking** — killing a `terraform` process mid-run leaves a stale lock in DynamoDB. Use `terraform force-unlock <lock-id>` or delete the item directly from the DynamoDB table.
- **Golden AMI staleness** — an AMI captures instance state at a point in time. Any configuration done after the AMI was created is lost if the ASG replaces the instance. Recreate the AMI after major changes.
- **AWS console vs CLI** — the console shows a simplified view. A MixedInstancesPolicy that overrides your launch template instance type is invisible in the console Details tab but visible in `aws autoscaling describe-auto-scaling-groups`.

-----

## Cost

### Primary region (always on)

|Resource        |Monthly cost  |
|----------------|--------------|
|EC2 t3.micro    |~$8           |
|RDS db.t4g.micro|~$14          |
|NAT Gateway     |~$32          |
|ALB             |~$16          |
|**Total**       |**~$70/month**|

### DR region (standby, ASG at 0)

|Resource              |Monthly cost  |
|----------------------|--------------|
|RDS read replica      |~$14          |
|ALB                   |~$16          |
|SSM VPC endpoints (x3)|~$21          |
|**Total**             |**~$51/month**|

To eliminate DR costs during development, run `terraform destroy` and rebuild when needed.

-----

## Author

**Ngozi Hannah Opara**
Cloud Engineer
[GitHub: CloudWithHannah](https://github.com/CloudWithHannah)
