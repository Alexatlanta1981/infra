# v1.0 Proof of Deployment — 2026-10-04T22:10:33Z

## CI/CD run (GitHub Actions)
CI/CD — api-gateway | branch=main | workflow_dispatch | success | 2026-10-04T22:03:47Z
https://github.com/Alexatlanta1981/backend/actions/runs/37238554778
  job: Build & Security Gates (api-gateway) / Build · SAST · Scan · Push · Sign (api-gateway) -> success
  job: 🚀 Deploy api-gateway → DEV -> success

## GitOps commit
ci(dev): update api-gateway → sha-beb1e4e @ 2026-10-04T22:05:20Z

## Argo CD applications
NAME                        SYNC STATUS   HEALTH STATUS
api-gateway-dev             Synced        Healthy
auth-service-dev            Synced        Healthy
catalog-service-dev         Synced        Healthy
inventory-service-dev       Synced        Healthy
manufacturing-service-dev   Synced        Healthy
notification-service-dev    Synced        Healthy
mackllc-ui-dev               Synced        Healthy
qc-service-dev              Synced        Healthy
supplier-service-dev        Synced        Healthy

## Pods (dev)
NAME                                     READY   STATUS    RESTARTS   AGE
api-gateway-5bd649ccb6-797w8             1/1     Running   0          3m24s
auth-service-7d9fd74d97-hqqlm            1/1     Running   0          105m
drug-catalog-service-7978784985-cg5sd    1/1     Running   0          105m
inventory-service-6b7bc696d7-h57d6       1/1     Running   0          105m
manufacturing-service-765f7cf946-6k9bq   1/1     Running   0          105m
notification-service-69f9f554f8-gcbcr    1/1     Running   0          132m
mackllc-ui-79f76586bf-w69w4               1/1     Running   0          98m
qc-service-598f97d6cb-gnf84              1/1     Running   0          132m
supplier-service-6775468585-vg78s        1/1     Running   0          105m

## Deployed image
<account-id>.dkr.ecr.us-east-1.amazonaws.com/api-gateway:sha-beb1e4e

## Ingress / ALB
NAME          CLASS   HOSTS   ADDRESS                                                           PORTS   AGE
api-gateway   alb     *       <ALB_HOSTNAME>   80      132m
mackllc-ui     alb     *       <ALB_HOSTNAME>   80      102m

## ECR images
api-gateway: 10 images
auth-service: 4 images
mackllc-ui: 2 images
i/drugs -> 401
GET /api/inventory -> 401
GET /actuator/health -> 200
(401 on /api/* = gateway reached and correctly demands a login token; not a 502/503)
