# PrisHistorie Kubernetes

This directory contains the Kubernetes configuration for running PrisHistorie
locally using Kind and Cilium.

## 1. Create the cluster

```powershell
kind create cluster --name prishistorie --config .\kubernetes\cluster.yaml
```

## 2. Install Cilium

The Kind cluster is created with the default CNI disabled.
Cilium must therefore be installed before deploying the application.

```powershell
helm repo add cilium https://helm.cilium.io/
helm repo update

helm install cilium cilium/cilium `
  --namespace kube-system `
  --set kubeProxyReplacement=true `
  --set ingressController.enabled=true `
  --set ingressController.loadbalancerMode=dedicated
```

## 3. Verify cluster and storage

Wait until the nodes are `Ready`:

```powershell
kubectl get nodes
kubectl get pods -n kube-system
```

Verify that the default `standard` StorageClass is available:

```powershell
kubectl get storageclass
```

## 4. Build and load local images

Build the PrisHistorie Docker images:

```powershell
docker compose build
```

Kind nodes use their own container runtime, so locally built Docker images
must explicitly be loaded into the cluster:

```powershell
kind load docker-image prishistorie-prishistorie-api --name prishistorie
kind load docker-image prishistorie-prishistorie-cron --name prishistorie
```

## 5. Create namespace

```powershell
kubectl apply -f .\kubernetes\namespace.yaml
```

## 6. Create secrets

Create `prishistorie-secrets` before starting the CronJob.

See `secret.example.yaml` for the required values.

Do not commit real API keys or passwords to Git.

## 7. Deploy PrisHistorie

```powershell
kubectl apply -f .\kubernetes\pvc.yaml
kubectl apply -f .\kubernetes\api.yaml
kubectl apply -f .\kubernetes\service.yaml
kubectl apply -f .\kubernetes\ingress.yaml
kubectl apply -f .\kubernetes\cronjob.yaml
```

## 8. Verify the deployment

```powershell
kubectl get pods -n prishistorie
kubectl get services -n prishistorie
kubectl get ingress -n prishistorie
kubectl get cronjobs -n prishistorie
```

The API should be available at:

```text
http://localhost:31072/CheckServer
```

## SQLite data

PrisHistorie currently uses SQLite. The database is stored on the
`prishistorie-data` PersistentVolumeClaim and mounted as `/app/data`
by both the API and CronJob.

### Copy an existing database to Kubernetes

Create the PVC first:

```powershell
kubectl apply -f .\kubernetes\pvc.yaml
```

The `pvc-loader` utility pod can be used to access the PVC:

```powershell
kubectl apply -f .\kubernetes\pvc-loader.yaml
```

Copy the existing database to the current directory:

```powershell
Copy-Item "C:\docker-backup\mindb\PrisHistorie.db" ".\PrisHistorie.db"
```

Then copy it into the PVC:

```powershell
kubectl cp .\PrisHistorie.db prishistorie/pvc-loader:/data/PrisHistorie.db
```

Verify that the database exists:

```powershell
kubectl exec -n prishistorie pvc-loader -- ls -lh /data
```

The API and CronJob mount the same PVC at `/app/data`, so the database
will be available to both as:

```text
/app/data/PrisHistorie.db
```

### Copy the database out of Kubernetes

A copy of the database can also be retrieved for local inspection or backup:

```powershell
kubectl cp prishistorie/pvc-loader:/data/PrisHistorie.db .\PrisHistorie-k8s.db
```

Avoid copying the database while the CronJob is writing to it. Check the
current Jobs and Pods first:

```powershell
kubectl get jobs,pods -n prishistorie
```

The local Kind PVC is intended for development and should not be considered
a backup of the database. Deleting/recreating the Kind cluster may also
delete the stored data.
